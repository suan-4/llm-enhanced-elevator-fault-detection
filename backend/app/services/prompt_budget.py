"""Local-only token budget. Calibration is evidence, never a character estimate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROBE_GROUPS = frozenset(('chinese', 'english', 'digits_symbols', 'report_all_fit',
                          'report_selected_risks', 'report_match_risk', 'report_natural_language'))


class ModelInputError(RuntimeError):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.details = details


def _integer(value, minimum=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def calibration_profile(samples, *, tokenizer_sha256, model_id, context_size, template_reserve):
    """Validate numeric SDK observations. The CLI supplies them from real requests.

    This function does not itself certify observations' origin; never pass a
    fixture to the deployment tool and label it a measured calibration.
    """
    if (not _sha(tokenizer_sha256) or not isinstance(model_id, str) or not model_id
            or not _integer(context_size, 1) or not _integer(template_reserve)
            or template_reserve >= context_size or not isinstance(samples, list)):
        raise ModelInputError('tokenizer_uncalibrated', '分词校准配置无效')
    evidence = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise ModelInputError('tokenizer_uncalibrated', '分词校准记录无效')
        count, actual = sample.get('input_tokens'), sample.get('sdk_input_tokens')
        if (sample.get('sdk_finished') is not True or not _integer(count, 1)
                or not _integer(actual, 1) or not _sha(sample.get('text_sha256'))
                or sample.get('group') not in PROBE_GROUPS
                or not 0 <= actual-count <= template_reserve
                or actual >= context_size):
            raise ModelInputError('tokenizer_uncalibrated', '分词结果与SDK不一致或未正常完成，不能启用校准')
        evidence.append({key:sample[key] for key in
                         ('group', 'text_sha256', 'input_tokens', 'sdk_input_tokens', 'sdk_finished')})
    if {sample['group'] for sample in evidence} != PROBE_GROUPS:
        raise ModelInputError('tokenizer_uncalibrated', '分词校准样本未覆盖全部要求场景')
    return dict(schema_version=1, status='calibrated', tokenizer_sha256=tokenizer_sha256,
                model_id=model_id, context_size=context_size, template_reserve=template_reserve,
                samples=evidence)


def load_tokenizer(path: Path, expected_sha256: str):
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ModelInputError('tokenizer_unavailable', '本机离线分词文件不可用，尚未调用模型') from error
    if not _sha(expected_sha256) or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ModelInputError('tokenizer_mismatch', '本机分词文件校验失败，尚未调用模型')
    try:
        from tokenizers import Tokenizer
        # Parse the bytes whose SHA was checked, not a second mutable path read.
        tokenizer = Tokenizer.from_str(raw.decode('utf8'))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return tokenizer
    except Exception as error:
        raise ModelInputError('tokenizer_unavailable', '本机分词组件或文件无效，尚未调用模型') from error


class PromptBudget:
    """An immutable per-service configuration; restart after changing its assets."""
    def __init__(self, tokenizer_path: Path, profile_path: Path, *, expected_sha256: str,
                 model_id: str, context_size=4096, output_tokens=512, template_reserve=128):
        self.tokenizer_path, self.profile_path = Path(tokenizer_path), Path(profile_path)
        self.expected_sha256, self.model_id = expected_sha256, model_id
        self.context_size, self.output_tokens, self.template_reserve = context_size, output_tokens, template_reserve
        self._tokenizer = None

    def _load(self):
        if (not _integer(self.context_size, 1) or not _integer(self.output_tokens, 1)
                or not _integer(self.template_reserve)
                or self.output_tokens+self.template_reserve >= self.context_size):
            raise ModelInputError('model_budget_config_invalid', '模型输入与回答预算配置无效，尚未调用模型')
        if self._tokenizer is not None:
            return
        tokenizer = load_tokenizer(self.tokenizer_path, self.expected_sha256)
        try:
            profile = json.loads(self.profile_path.read_text(encoding='utf8'))
            rebuilt = calibration_profile(profile['samples'], tokenizer_sha256=self.expected_sha256,
                                            model_id=self.model_id, context_size=self.context_size,
                                            template_reserve=self.template_reserve)
            if any(profile.get(key) != value for key, value in rebuilt.items()):
                raise ValueError('Calibration binding differs')
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ModelInputError('tokenizer_uncalibrated', '本机分词器尚未完成当前模型的有效校准，尚未调用模型') from error
        self._tokenizer = tokenizer

    def check(self, text: str) -> dict:
        self._load()
        if not isinstance(text, str) or len(text.encode('utf8')) > 1_000_000:
            raise ModelInputError('context_budget_exceeded', '模型输入过长，未截断原始资料，尚未调用模型')
        count = len(self._tokenizer.encode(text, add_special_tokens=False).ids)
        limit = self.context_size-self.output_tokens-self.template_reserve
        details = dict(input_tokens=count, input_budget_tokens=limit,
                       context_tokens=self.context_size, reserved_output_tokens=self.output_tokens,
                       template_reserve_tokens=self.template_reserve, tokenizer_sha256=self.expected_sha256)
        if count > limit:
            raise ModelInputError('context_budget_exceeded',
                                  f'模型输入为{count} token，超过输入预算{limit}；未截断原始资料', **details)
        return details

    def verify_model_id(self, model_ids):
        self._load()
        if not isinstance(model_ids, list) or self.model_id not in model_ids:
            raise ModelInputError('model_mismatch', '当前模型与分词校准记录不匹配，尚未调用模型')


def configured_budget():
    from app.config import settings
    root = Path(__file__).resolve().parents[2]
    try:
        source = json.loads((Path(__file__).resolve().parents[1]/'data/tokenizer-source.json').read_text(encoding='utf8'))
        expected = source['files']['tokenizer.json']['sha256']
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ModelInputError('tokenizer_unavailable', '离线分词器来源清单无效，尚未调用模型') from error
    def resolve(value):
        path = Path(value)
        return path if path.is_absolute() else root/path
    return PromptBudget(resolve(settings.rkllm_tokenizer_path), resolve(settings.rkllm_calibration_path),
                        expected_sha256=expected, model_id=settings.rkllm_model_id,
                        context_size=settings.rkllm_context_tokens, output_tokens=settings.rkllm_max_new_tokens,
                        template_reserve=settings.rkllm_template_reserve_tokens)

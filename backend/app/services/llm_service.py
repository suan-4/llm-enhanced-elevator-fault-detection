import json
import httpx
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit

from app.config import settings
from app.services.performance import record_model_call, current_purpose
from app.services.prompt_budget import ModelInputError, configured_budget

_RUNTIME_FIELDS = (
    'prefill_time_ms', 'prefill_tokens', 'generate_time_ms', 'generate_tokens',
    'memory_usage_mb', 'first_output_ms', 'model_run_ms', 'model_load_ms',
    'prefill_tokens_per_s', 'generate_tokens_per_s', 'perf_source', 'run_status',
    'inference_id', 'request_total_ms',
)


def build_content(prompt_json: str) -> str:
    """One final string for both local encoding and transmission; no truncation."""
    try:
        parsed = json.loads(prompt_json)
    except json.JSONDecodeError:
        parsed = {'system':'', 'data':prompt_json}
    if not isinstance(parsed, dict) or not isinstance(parsed.get('system', ''), str):
        raise ModelInputError('invalid_model_prompt', '模型输入结构无效')
    data = json.dumps(parsed.get('data', parsed), ensure_ascii=False, separators=(',', ':'))
    system = parsed.get('system', '')
    return system+'\n\n'+data if system else data


class LLMService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._budget = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.rkllm_timeout,
                                      connect=settings.rkllm_connect_timeout),
                trust_env=False,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def generate(self, prompt_json: str, max_tokens: int | None = None) -> str:
        """调用 RKLLM 服务器生成报告。

        prompt_json 格式: {"system": "...", "data": {...}}
        """
        build_started = perf_counter()
        # RKLLM Flask ignores system messages; send the same final text we count.
        full_content = build_content(prompt_json)
        messages = [{"role": "user", "content": full_content}]

        payload = {
            "model": "elevator-report",
            "messages": messages,
            "stream": False,
            "enable_thinking": False,
            "tools": None,
        }

        call = {'purpose':current_purpose(), 'input_chars':len(full_content),
                'input_utf8_bytes':len(full_content.encode('utf-8')),
                'request_build_ms':round((perf_counter()-build_started)*1000, 3),
                'status':'error', 'http_status':None, 'runtime':None}
        http_started = None
        try:
            budget_started = perf_counter()
            if self._budget is None:
                self._budget = configured_budget()
            call.update(self._budget.check(full_content))
            call['budget_ms'] = round((perf_counter()-budget_started)*1000, 3)
            payload['max_tokens'] = (min(self._budget.output_tokens, max_tokens)
                                     if max_tokens else self._budget.output_tokens)
            endpoint = urlsplit(settings.rkllm_server_url)
            identity_url = urlunsplit((endpoint.scheme, endpoint.netloc, '/v1/models', '', ''))
            http_started = perf_counter()
            identity = await self.client.get(identity_url)
            identity.raise_for_status()
            self._budget.verify_model_id([row.get('id') for row in identity.json().get('data', []) if isinstance(row, dict)])
            response = await self.client.post(
                settings.rkllm_server_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            call['http_status'] = response.status_code
            response.raise_for_status()
            data_resp = response.json()
            runtime = data_resp.get('performance')
            if isinstance(runtime, dict):
                call['runtime'] = {key:runtime.get(key) for key in _RUNTIME_FIELDS}
            choices = data_resp.get("choices", [])
            content = choices[-1].get('message', {}).get('content') if choices else None
            if not isinstance(content, str) or not content.strip():
                raise ModelInputError('model_empty_response', '模型返回空内容，未成功生成概况')
            if not isinstance(runtime, dict) or runtime.get('run_status') != 'finished':
                raise ModelInputError('model_not_finished', '模型未正常完成推理，不能采用返回内容')
            # 达到 max_tokens 时仍保留已生成内容；字数长短不再作为失败条件。
            call['status'] = 'ok'
            return content
        except ModelInputError as error:
            call['error_code'] = error.code
            call.update(error.details)
            raise
        except httpx.ConnectError:
            call['error_code'] = 'model_unavailable'
            raise ModelInputError('model_unavailable', '无法连接本机模型服务') from None
        except httpx.TimeoutException:
            call['error_code'] = 'model_timeout'
            raise ModelInputError('model_timeout', '模型服务响应超时') from None
        except Exception:
            call['error_code'] = 'model_response_invalid'
            raise ModelInputError('model_response_invalid', '模型服务请求失败或返回格式无效') from None
        finally:
            call['http_ms'] = round((perf_counter()-http_started)*1000, 3) if http_started is not None else 0
            record_model_call(call)

    async def generate_or_fallback(self, prompt_json: str) -> str:
        """调用 RKLLM，失败时返回图谱数据的结构化展示。"""
        try:
            return await self.generate(prompt_json)
        except RuntimeError:
            return self._fallback_response(prompt_json)

    def _fallback_response(self, prompt_json: str) -> str:
        try:
            parsed = json.loads(prompt_json)
            data = parsed.get("data", {})
        except json.JSONDecodeError:
            data = {}

        lines = ["[RKLLM模型暂不可用，以下为知识图谱查询结果]\n"]
        items = data.get("failed_inspection_items", [])
        for item in items:
            lines.append(f"## {item['item']}")
            for s in item.get("states", []):
                lines.append(f"- 部件: {s['component']}")
                lines.append(f"- 状态: {s['state']} (严重度{s['severity']})")
                if s.get("phenomena"):
                    lines.append(f"- 现象: {', '.join(s['phenomena'])}")
                if s.get("risks"):
                    risks_str = ", ".join(f"{r['name']}[{r.get('level','')}]" for r in s["risks"])
                    lines.append(f"- 风险: {risks_str}")
                if s.get("suggested_actions"):
                    acts_str = ", ".join(a["name"] for a in s["suggested_actions"])
                    lines.append(f"- 建议: {acts_str}")
                lines.append("")
        return "\n".join(lines)


    async def generate_stream(self, prompt_json: str):
        """流式调用 RKLLM，yield 文本块。"""
        try:
            parsed = json.loads(prompt_json)
        except json.JSONDecodeError:
            parsed = {"system": "", "data": prompt_json}

        system_prompt = parsed.get("system", "")
        data = parsed.get("data", parsed)
        user_content = json.dumps(data, ensure_ascii=False, indent=2)

        # RKLLM Flask 忽略 system 消息，直接拼到 user 前面
        full_content = (system_prompt + "\n\n" + user_content) if system_prompt else user_content
        messages = [{"role": "user", "content": full_content}]

        payload = {
            "model": "elevator-report",
            "messages": messages,
            "stream": True,
            "enable_thinking": False,
            "tools": None,
        }

        async with self.client.stream("POST", settings.rkllm_server_url, json=payload,
                                        headers={"Content-Type": "application/json"},
                                        timeout=httpx.Timeout(
                                            settings.rkllm_timeout,
                                            connect=settings.rkllm_connect_timeout)) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    line = line[6:]
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[-1].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                except json.JSONDecodeError:
                    continue


llm_service = LLMService()

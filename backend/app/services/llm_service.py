import json
import httpx

from app.config import settings


class LLMService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.rkllm_timeout),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def generate(self, prompt_json: str) -> str:
        """调用 RKLLM 服务器生成报告。

        prompt_json 格式: {"system": "...", "data": {...}}
        """
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
            "stream": False,
            "enable_thinking": False,
            "tools": None,
        }

        try:
            response = await self.client.post(
                settings.rkllm_server_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data_resp = response.json()
            choices = data_resp.get("choices", [])
            if choices:
                return choices[-1].get("message", {}).get("content", "")
            return ""
        except httpx.ConnectError:
            raise RuntimeError(
                f"无法连接RKLLM服务器({settings.rkllm_server_url})，请确认板卡已启动且网络可达"
            )
        except httpx.TimeoutException:
            raise RuntimeError("RKLLM服务器响应超时")
        except Exception as e:
            raise RuntimeError(f"RKLLM调用失败: {str(e)}")

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
                                        timeout=httpx.Timeout(settings.rkllm_timeout)) as response:
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

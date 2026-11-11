from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict

from ten_runtime import AsyncTenEnv


class MemoryStore(ABC):
    def __init__(self, env: AsyncTenEnv):
        self.env: AsyncTenEnv = env

    @abstractmethod
    async def add(
        self,
        conversation: list[dict],
        user_id: str,
        agent_id: str,
    ) -> None: ...

    @abstractmethod
    async def search(self, user_id: str, agent_id: str, query: str) -> Any: ...

    @abstractmethod
    async def get_user_profile(self, user_id: str, agent_id: str) -> str: ...


class EverMemosMemoryStore(MemoryStore):
    """EverMemOS SDK memory store implementation."""

    def __init__(self, config: Dict[str, Any], env: AsyncTenEnv):
        super().__init__(env)
        from everos_cloud import EverOS

        # 从配置中获取 API key
        api_key = config.get("api_key", "")
        if not api_key:
            raise ValueError("EverMemOS API key is required in config")

        self.client = EverOS(api_key=api_key)
        self.session_id = uuid.uuid4().hex
        self.env.log_info(
            "[EverMemosMemoryStore] Initialized EverOS Cloud client"
        )

    async def add(
        self,
        conversation: list[dict],
        user_id: str,
        agent_id: str,
    ) -> None:
        """Add conversation to EverMemOS using the EverOS Cloud SDK."""
        self.env.log_info(
            f"╔══════════════════════════════════════════════════════════════════╗\n"
            f"║                [EverMemOS] 保存对话到记忆                          ║\n"
            f"╠══════════════════════════════════════════════════════════════════╣\n"
            f"║ 👤 User ID:     '{user_id}'                                       ║\n"
            f"║ 🤖 Agent ID:    '{agent_id}'                                      ║\n"
            f"║ 💬 Conversation Length: {len(conversation)} 条消息                           ║\n"
            f"╚══════════════════════════════════════════════════════════════════╝"
        )

        if not conversation:
            self.env.log_warn(
                "[EverMemosMemoryStore] Empty conversation, skipping"
            )
            return

        try:
            group_id = f"{user_id}_{agent_id}"
            base_ts = int(time.time() * 1000)

            self.env.log_info(
                f"[EverMemOS] 📝 准备保存 {len(conversation)} 条消息:"
            )

            for i, msg in enumerate(conversation):
                try:
                    payload = {
                        "timestamp": base_ts + i,
                        "sender_id": (
                            user_id if msg["role"] == "user" else agent_id
                        ),
                        "sender_name": (
                            "User" if msg["role"] == "user" else "Assistant"
                        ),
                        "role": msg["role"],
                        "content": msg["content"],
                    }

                    response = await asyncio.to_thread(
                        self.client.add,
                        session_id=self.session_id,
                        project_id=group_id,
                        messages=[payload],
                        async_mode=False,
                    )
                    if i == len(conversation) - 1:
                        await asyncio.to_thread(
                            self.client.flush,
                            self.session_id,
                            project_id=group_id,
                        )
                    self.env.log_info(
                        f"    [{i+1}/{len(conversation)}] "
                        f"[{payload['sender_name']}] {payload['content'][:50]}..."
                    )
                    self.env.log_info(
                        f"         └─ API响应: status={response.status}"
                    )
                except Exception as e:
                    self.env.log_error(
                        f"[EverMemosMemoryStore] ❌ 保存消息 {i} 失败: {e}"
                    )

            self.env.log_info(
                f"[EverMemOS] ✅ 成功保存 {len(conversation)} 条消息到用户 '{user_id}' 的记忆"
            )
        except Exception as e:
            self.env.log_error(
                f"[EverMemosMemoryStore] Failed to add conversation: {e}"
            )
            import traceback

            self.env.log_error(
                f"[EverMemosMemoryStore] Traceback: {traceback.format_exc()}"
            )
            raise

    async def search(self, user_id: str, agent_id: str, query: str) -> Any:
        """Search memories using EverMemOS SDK."""
        self.env.log_info(
            f"╔══════════════════════════════════════════════════════════════════╗\n"
            f"║                [EverMemOS] 搜索相关记忆                          ║\n"
            f"╠══════════════════════════════════════════════════════════════════╣\n"
            f"║ 👤 User ID:     '{user_id}'                                       ║\n"
            f"║ 🤖 Agent ID:    '{agent_id}'                                      ║\n"
            f"║ 🔍 Search Query: '{query}'                                       ║\n"
            f"╚══════════════════════════════════════════════════════════════════╝"
        )

        try:
            response = await asyncio.to_thread(
                self.client.search,
                query,
                user_id=user_id,
                project_id=f"{user_id}_{agent_id}",
                method="hybrid",
                top_k=10,
            )

            # 转换为统一格式
            result = {"results": []}
            memories_found = 0

            self.env.log_info(f"[EverMemOS] 📊 搜索结果详情:")

            if response.episodes:
                memories = response.episodes

                self.env.log_info(
                    f"    ┌──────────────────────────────────────────────────────────────────┐"
                )
                self.env.log_info(
                    f"    │ 返回记忆对象类型: {type(memories[0]) if memories else 'N/A'}      │"
                )

                # 处理 ResultMemoryEpisodicMemoryModel 对象列表（新版 SDK）
                for i, mem in enumerate(memories):
                    # 使用 getattr 获取对象属性
                    summary = getattr(mem, "summary", "")
                    episode = getattr(mem, "episode", "")
                    subject = getattr(mem, "subject", "")
                    score = getattr(mem, "score", 0)
                    timestamp = getattr(mem, "timestamp", "")
                    memory_id = getattr(mem, "id", "")

                    # 优先使用 episode (详细内容)，如果没有则使用 summary
                    memory_text = episode if episode else summary

                    if memory_text:
                        memories_found += 1
                        result["results"].append(
                            {
                                "memory": memory_text,
                                "score": score,
                                "timestamp": str(timestamp),
                                "subject": subject,
                                "id": memory_id,
                            }
                        )

                        # 打印前5条记忆的详细信息
                        if memories_found <= 5:
                            self.env.log_info(
                                f"    │ #{memories_found} [score={score:.4f}] ts={timestamp}                    │"
                            )
                            self.env.log_info(
                                f"    │     主题: {subject[:50]}...                       │"
                            )
                            self.env.log_info(
                                f'    │     内容: "{memory_text[:50]}..."                       │'
                            )

                self.env.log_info(
                    f"    └──────────────────────────────────────────────────────────────────┘"
                )

            if memories_found > 0:
                self.env.log_info(
                    f"[EverMemOS] ✅ 搜索完成! 为用户 '{user_id}' 找到 {memories_found} 条相关记忆"
                )
            else:
                self.env.log_info(
                    f"[EverMemOS] ℹ️ 搜索完成! 用户 '{user_id}' 没有找到相关记忆"
                )
            return result

        except Exception as e:
            self.env.log_error(
                f"[EverMemosMemoryStore] Failed to search memories: {e}"
            )
            import traceback

            self.env.log_error(
                f"[EverMemosMemoryStore] Traceback: {traceback.format_exc()}"
            )
            return {"results": []}

    async def get_user_profile(self, user_id: str, agent_id: str) -> str:
        """Get user profile from EverMemOS."""
        self.env.log_info(
            f"╔══════════════════════════════════════════════════════════════════╗\n"
            f"║                [EverMemOS] 获取用户资料                          ║\n"
            f"╠══════════════════════════════════════════════════════════════════╣\n"
            f"║ 👤 User ID:     '{user_id}'                                       ║\n"
            f"║ 🤖 Agent ID:    '{agent_id}'                                      ║\n"
            f"╚══════════════════════════════════════════════════════════════════╝"
        )

        try:
            # Search for user profile
            user_profile = await self.search(
                user_id=user_id,
                agent_id=agent_id,
                query="User Profile",
            )

            # Extract memory content from results
            results = user_profile.get("results", [])
            self.env.log_info(
                f"[EverMemOS] 📋 找到 {len(results)} 条用户资料记忆"
            )

            memorise = [
                result["memory"]
                for result in results
                if isinstance(result, dict) and result.get("memory")
            ]

            # Format memory text
            if memorise:
                profile_content = (
                    "User Profile:\n"
                    + "\n".join(f"- {memory}" for memory in memorise)
                    + "\n"
                )
                self.env.log_info(
                    f"[EverMemOS] ✅ 成功格式化 {len(memorise)} 条用户资料"
                )
            else:
                profile_content = ""
                self.env.log_info(
                    f"[EverMemOS] ℹ️ 用户 '{user_id}' 没有找到用户资料"
                )

            return profile_content

        except Exception as e:
            self.env.log_error(
                f"[EverMemosMemoryStore] Failed to get user profile: {e}"
            )
            import traceback

            self.env.log_error(
                f"[EverMemosMemoryStore] Traceback: {traceback.format_exc()}"
            )
            return ""

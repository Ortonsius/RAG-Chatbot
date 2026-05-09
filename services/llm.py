import json
import logging
import ollama
import os
from typing import List, Dict, Any, Optional, Callable, Awaitable
import asyncio

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self):
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = os.getenv("LLM_MODEL", "qwen3.5:9b")
        self.embed_model = os.getenv("EMBED_MODEL", "qwen3-embedding:4b")
        self.client = ollama.Client(host=self.host)
        logger.info(f"LLMService initialized with model {self.model} and embedder {self.embed_model}")

    def get_embedding(self, text: str) -> List[float]:
        try:
            response = self.client.embeddings(model=self.embed_model, prompt=text)
            return response["embedding"]
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            raise

    async def chat_with_tools(
        self,
        user_message: str,
        system_prompt: str,
        context: str = "",
        history: List[Dict] = None,
        tools: List[Dict] = None,
        tool_handler: Callable[[str, Dict], Awaitable[str]] = None,
        max_tool_calls: int = 12
    ) -> str:
        messages = self._build_messages(system_prompt, context, history, user_message)
        tool_calls_made = 0
        loop = asyncio.get_running_loop()

        while tool_calls_made < max_tool_calls:
            if asyncio.current_task().cancelled():
                raise asyncio.CancelledError()
            
            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat(
                    model=self.model,
                    messages=messages,
                    tools=tools or [],
                    options={"temperature": 0.3}
                )
            )
            
            message = response["message"]
            messages.append(message)

            if message.get("tool_calls"):
                tool_calls_made += 1
                logger.info(f"Tool call round {tool_calls_made}: {len(message['tool_calls'])} tool(s) requested.")
                
                for tool_call in message["tool_calls"]:
                    function = tool_call["function"]
                    tool_name = function["name"]
                    arguments = function["arguments"]
                    
                    logger.info(f"Executing tool: {tool_name} with args: {arguments}")
                    
                    if asyncio.current_task().cancelled():
                        raise asyncio.CancelledError()
                    
                    tool_result = await tool_handler(tool_name, arguments)
                    
                    messages.append({
                        "role": "tool",
                        "tool_name": tool_name,
                        "content": tool_result
                    })
                continue
            else:
                return message["content"]
        
        logger.warning(f"Reached maximum tool calls ({max_tool_calls}). Forcing final answer.")
        if asyncio.current_task().cancelled():
            raise asyncio.CancelledError()
        final_response = await loop.run_in_executor(
            None,
            lambda: self.client.chat(
                model=self.model,
                messages=messages + [{"role": "user", "content": "Please provide a final answer now."}],
                options={"temperature": 0.3}
            )
        )
        return final_response["message"]["content"]

    def _build_messages(self, system_prompt: str, context: str, history: List[Dict], user_message: str) -> List[Dict]:
        messages = [{"role": "system", "content": system_prompt}]
        if context:
            messages.append({"role": "system", "content": f"Relevant context from memory:\n{context}"})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages
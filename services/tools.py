import asyncio
import logging
import os
from typing import Tuple
import docker
from docker.errors import NotFound, APIError
from aiogram import Bot
from aiogram.types import FSInputFile
from services.memory import MemoryService

logger = logging.getLogger(__name__)

_docker_client = None

def get_docker_client():
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client

async def ensure_sandbox_container():
    client = get_docker_client()
    container_name = os.getenv("DOCKER_CONTAINER_NAME", "autoai_sandbox")
    image = os.getenv("DOCKER_IMAGE", "autoai_sandbox:latest")
    workdir = os.getenv("DOCKER_WORKDIR", "/workspace")
    host_volume = os.getenv("DOCKER_VOLUME_HOST", "./workspace")
    container_volume = os.getenv("DOCKER_VOLUME_CONTAINER", "/workspace")
    os.makedirs(host_volume, exist_ok=True)
    
    try:
        container = client.containers.get(container_name)
        if container.status != "running":
            logger.info(f"Starting existing container '{container_name}'")
            container.start()
        return container
    except NotFound:
        logger.info(f"Creating new sandbox container '{container_name}'")
        try:
            client.images.get(image)
        except docker.errors.ImageNotFound:
            logger.info(f"Pulling image '{image}'...")
            client.images.pull(image)
        
        container = client.containers.run(
            image,
            command="tail -f /dev/null",
            name=container_name,
            volumes={os.path.abspath(host_volume): {"bind": container_volume, "mode": "rw"}},
            working_dir=workdir,
            detach=True,
            remove=False,
            tty=True
        )
        logger.info(f"Container '{container_name}' created and running.")
        return container

async def execute_linux_command(command: str) -> Tuple[str, str]:
    try:
        container = await ensure_sandbox_container()
        loop = asyncio.get_running_loop()
        
        def run_in_container():
            exec_result = container.exec_run(
                f"/bin/bash -c '{command}'",
                stdout=True,
                stderr=True,
                workdir=os.getenv("DOCKER_WORKDIR", "/workspace")
            )
            stdout = exec_result.output.decode('utf-8', errors='replace').strip()
            stderr = "" if exec_result.exit_code == 0 else stdout
            if exec_result.exit_code != 0:
                stdout = ""
            return stdout, stderr
        
        stdout, stderr = await loop.run_in_executor(None, run_in_container)
        logger.info(f"Executed command in container: {command}")
        return stdout, stderr
    except Exception as e:
        logger.error(f"Command execution failed: {e}")
        raise

async def write_python_script(script_content: str, filename: str) -> str:
    if "/" in filename or "\\" in filename:
        raise ValueError("Filename cannot contain path separators.")
    
    host_volume = os.getenv("DOCKER_VOLUME_HOST", "./workspace")
    scripts_dir = os.path.join(host_volume, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    filepath = os.path.join(scripts_dir, filename)
    
    try:
        with open(filepath, "w") as f:
            f.write(script_content)
        logger.info(f"Python script written to {filepath}")
        return f"Script successfully written to {filepath} (accessible inside container at /workspace/scripts/{filename})"
    except Exception as e:
        logger.error(f"Failed to write script: {e}")
        raise

async def add_to_memory(text: str, source: str = "llm_generated") -> int:
    memory = MemoryService()
    return await memory.add_document(text, {"source": source})

async def update_memory(filter_source: str, new_text: str) -> int:
    memory = MemoryService()
    return await memory.update_by_source(filter_source, new_text)

async def delete_from_memory(source: str) -> int:
    memory = MemoryService()
    return await memory.delete_by_filename(source)

async def send_file_to_user(bot: Bot, chat_id: int, file_path: str):
    allowed_base = os.path.abspath(os.getenv("DOCKER_VOLUME_HOST", "./workspace"))
    abs_path = os.path.abspath(file_path)
    if not abs_path.startswith(allowed_base):
        raise ValueError(f"File path {file_path} is outside allowed workspace.")
    
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"File {abs_path} does not exist.")
    
    document = FSInputFile(abs_path)
    await bot.send_document(chat_id, document)
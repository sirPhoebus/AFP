"""Docker-backed task execution for unit evidence capture."""

from dataclasses import dataclass
from subprocess import CompletedProcess, run


@dataclass(frozen=True)
class ContainerExecutionResult:
    exit_code: int
    output: str


def run_container_command(image: str, command: list[str], workdir: str | None = None) -> ContainerExecutionResult:
    docker_command = ["docker", "run", "--rm"]
    if workdir is not None:
        docker_command.extend(["-v", f"{workdir}:/workspace", "-w", "/workspace"])
    docker_command.append(image)
    docker_command.extend(command)
    completed: CompletedProcess[str] = run(docker_command, capture_output=True, text=True, check=False)
    output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part).strip()
    return ContainerExecutionResult(exit_code=completed.returncode, output=output)

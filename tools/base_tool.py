"""Base tool definition for AI Workforce agents."""

import abc
import logging
from typing import Any, Dict, NamedTuple

logger = logging.getLogger("ai_workforce.tools.base_tool")


class ToolResult(NamedTuple):
    success: bool
    data: Any
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
        }


class BaseAgentTool(abc.ABC):
    """
    Classe base para todas as ferramentas utilizadas pelos agentes de IA.
    Compatível com CrewAI Tools e chamada direta.
    """

    name: str = "base_tool"
    description: str = "Ferramenta base do AI Workforce."
    version: str = "1.0.0"

    def validate_inputs(self, **kwargs) -> bool:
        """Valida os parâmetros antes da execução."""
        return True

    @abc.abstractmethod
    def execute(self, **kwargs) -> Any:
        """Implementação da lógica da ferramenta."""
        raise NotImplementedError

    def run(self, **kwargs) -> ToolResult:
        """Executa a ferramenta com tratamento robusto de erros e logging."""
        try:
            if not self.validate_inputs(**kwargs):
                return ToolResult(success=False, data=None, error=f"Parâmetros inválidos para a ferramenta {self.name}.")
            result = self.execute(**kwargs)
            return ToolResult(success=True, data=result, error="")
        except Exception as error:
            logger.error(f"Erro ao executar a ferramenta {self.name}: {error}", exc_info=True)
            return ToolResult(success=False, data=None, error=str(error))

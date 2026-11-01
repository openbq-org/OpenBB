"""Validation models for MCP configuration structures."""

import re
from enum import StrEnum
from typing import Any

from fastmcp.utilities.logging import get_logger
from pydantic import BaseModel, Field, field_validator, model_validator

logger = get_logger(__name__)


class MCPType(StrEnum):
    """Valid MCP type values."""

    TOOL = "tool"
    RESOURCE = "resource"
    RESOURCE_TEMPLATE = "resource_template"


class HTTPMethod(StrEnum):
    """Valid HTTP methods for route configuration."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    ALL = "*"


class ArgumentDefinitionModel(BaseModel):
    """Model for validating prompt argument definitions."""

    name: str = Field(..., description="Name of the argument")
    type: str = Field(default="str", description="Type of the argument")
    default: Any | None = Field(
        default=None, description="Default value for the argument"
    )
    description: str | None = Field(
        default=None, description="Description of the argument"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate argument name is a valid identifier."""
        if not v:
            raise ValueError("Argument name cannot be empty")
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", v):
            raise ValueError(f"Argument name '{v}' must be a valid Python identifier")
        return v

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate type is a recognized type string."""
        valid_types = {
            "str",
            "string",
            "int",
            "integer",
            "float",
            "bool",
            "boolean",
            "list",
            "dict",
            "any",
            "Any",
        }
        if v not in valid_types:
            raise ValueError(
                f"Type '{v}' not recognized. Valid types: {', '.join(sorted(valid_types))}"
            )
        return v


class PromptConfigModel(BaseModel):
    """Model for validating individual prompt configurations."""

    name: str | None = Field(
        default=None, description="Name of the prompt (auto-generated if not provided)"
    )
    description: str | None = Field(
        default=None, description="Description of the prompt"
    )
    content: str = Field(description="Template content with {variable} placeholders")
    arguments: list[ArgumentDefinitionModel] = Field(
        default_factory=list, description="Argument definitions for the prompt"
    )
    tags: list[str] = Field(
        default_factory=list, description="Tags for categorizing the prompt"
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate content is not empty and contains valid template syntax."""
        if not v.strip():
            raise ValueError("Prompt content cannot be empty")

        open_braces = v.count("{")
        close_braces = v.count("}")
        if open_braces != close_braces:
            raise ValueError(
                f"Unmatched braces in prompt content: {open_braces} opening, {close_braces} closing"
            )

        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """Validate prompt name if provided."""
        if v is not None:
            if not v.strip():
                raise ValueError("Prompt name cannot be empty string")
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", v.strip()):
                raise ValueError(f"Prompt name '{v}' should be a valid identifier")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        """Validate tags are non-empty strings."""
        validated_tags = []
        for tag in v:
            if not tag.strip():
                raise ValueError("Tag cannot be empty string")
            validated_tags.append(tag.strip())
        return validated_tags


class MCPConfigModel(BaseModel):
    """Model for validating the main MCP configuration structure."""

    expose: bool | None = Field(
        default=None, description="Whether to expose this route (False = exclude)."
    )
    mcp_type: MCPType | None = Field(
        default=None, description="MCP type classification for the route."
    )
    methods: list[HTTPMethod] | None = Field(
        default=None, description="HTTP methods to include for this route."
    )
    prompts: list[PromptConfigModel] = Field(
        default_factory=list, description="Prompt configurations for this route."
    )
    exclude_args: list[str] | None = Field(
        default=None,
        description="Argument names left out of the tool's input schema; each needs a default.",
    )
    name: str | None = Field(
        default=None, description="Tool name, replacing the one built from the path."
    )
    tags: list[str] | None = Field(
        default=None, description="Tags added to the tool next to its category."
    )
    enable: bool | None = Field(
        default=None,
        description="Serve (True) or hide (False) the tool regardless of default_tool_categories.",
    )
    describe_responses: bool | None = Field(
        default=None,
        description="Keep (True) or cut (False) the response documentation in the tool description.",
    )
    mime_type: str | None = Field(
        default=None, description="MIME type of a route served as a resource."
    )

    @field_validator("methods", mode="before")
    @classmethod
    def validate_methods(cls, v: str | list[str] | None) -> list[HTTPMethod] | None:
        """Normalize and validate HTTP methods."""
        if v is None:
            return None

        if isinstance(v, str):
            v = [v]

        if not isinstance(v, list):
            raise ValueError("methods must be a list of strings")

        if "*" in v and len(v) > 1:
            raise ValueError("Method '*' cannot be mixed with other HTTP methods.")

        validated_methods = []
        for method in v:
            method_str = str(method).upper().strip() if method != "*" else "*"
            try:
                validated_methods.append(HTTPMethod(method_str))
            except ValueError as exc:
                valid_methods = [m.value for m in HTTPMethod]
                raise ValueError(
                    f"Invalid HTTP method '{method}'. Valid methods: {', '.join(valid_methods)}"
                ) from exc

        seen = set()
        unique_methods = []
        for method in validated_methods:
            if method not in seen:
                seen.add(method)
                unique_methods.append(method)

        return unique_methods if unique_methods else None

    @model_validator(mode="after")
    def validate_config_consistency(self) -> "MCPConfigModel":
        """Validate overall configuration consistency."""
        if self.prompts:
            prompt_names = []
            for prompt in self.prompts:
                if prompt.name:
                    prompt_names.append(prompt.name)

            if len(prompt_names) != len(set(prompt_names)):
                duplicates = [
                    name for name in prompt_names if prompt_names.count(name) > 1
                ]
                raise ValueError(f"Duplicate prompt names found: {set(duplicates)}")

        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format compatible with existing code."""
        return self.model_dump(exclude_none=True)


def validate_mcp_config(
    config_dict: dict[str, Any], *, strict: bool = True
) -> MCPConfigModel:
    """Validate an MCP configuration dictionary."""
    try:
        return MCPConfigModel.model_validate(config_dict)
    except Exception as exc:
        if strict:
            raise
        logger.warning("MCP config validation failed ->", exc_info=exc)
        return MCPConfigModel()


def is_valid_mcp_config(config_dict: dict[str, Any]) -> bool | Exception:
    """Check if a configuration dictionary is valid without raising exceptions."""
    try:
        validate_mcp_config(config_dict, strict=True)
        return True
    except Exception as exc:
        return exc

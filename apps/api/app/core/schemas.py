from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """API models use snake_case in Python and camelCase on the wire."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)

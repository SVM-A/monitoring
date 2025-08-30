from pydantic import BaseModel

class _BaseSchema(BaseModel):

    class Config:
        use_enum_values = True
        from_attributes = True
        extra = 'ignore'
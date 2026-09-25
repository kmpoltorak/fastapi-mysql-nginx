from typing import Any, Literal, Optional, List
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
import re


def validate_identifier(name: str) -> str:
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError(
            "Invalid identifier: must start with a letter or underscore and "
            "contain only letters, numbers, and underscores."
        )
    return name


def example(**kwargs) -> ConfigDict:
    return ConfigDict(json_schema_extra={"example": kwargs})


# User models
class UserBase(BaseModel):
    username: str
    email: str

    model_config = example(username="johndoe", email="john@example.com")


class UserCreate(UserBase):
    password: str

    model_config = example(username="johndoe", email="john@example.com",
                           password="strongpassword")


class UserUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None

    model_config = example(email="john@newmail.com", password="newpassword")


# Auth models
class LoginRequest(BaseModel):
    username: str
    password: str
    totp: Optional[str] = None

    model_config = example(username="admin", password="secret", totp="123456")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TotpEnableRequest(BaseModel):
    secret: str
    code: str

    model_config = example(secret="JBSWY3DPEHPK3PXP", code="123456")


# Unified API response model
class APIResponse(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None

    model_config = example(code=200, message="Success", data={"result": "example"})


# Database request models
class DatabaseRequest(BaseModel):
    database_name: str

    @field_validator('database_name')
    @classmethod
    def validate_database_name(cls, v):
        return validate_identifier(v)

    model_config = example(database_name="testdb")


class DatabaseBackupRequest(DatabaseRequest):
    pass


class DatabaseRestoreRequest(DatabaseRequest):
    sql_dump: str

    model_config = example(database_name="testdb", sql_dump="CREATE TABLE ...; INSERT INTO ...;")


# Table request models
class TableColumnField(BaseModel):
    name: str
    params: str

    @field_validator('name')
    @classmethod
    def validate_column_name(cls, v):
        return validate_identifier(v)

    model_config = example(name="id", params="INT PRIMARY KEY AUTO_INCREMENT")


class TableRequest(DatabaseRequest):
    table_name: str

    @field_validator('table_name')
    @classmethod
    def validate_table_name(cls, v):
        return validate_identifier(v)

    model_config = example(database_name="testdb", table_name="users")


class TableCreateRequest(TableRequest):
    columns: List[TableColumnField]

    model_config = example(
        database_name="testdb",
        table_name="users",
        columns=[
            {"name": "id", "params": "INT PRIMARY KEY AUTO_INCREMENT"},
            {"name": "username", "params": "VARCHAR(255) NOT NULL"}
        ]
    )


class TableAlterRequest(TableRequest):
    action: Literal["add", "modify", "drop", "rename"]
    column_name: str
    params: Optional[str] = None  # column definition, required for add/modify
    new_column_name: Optional[str] = None  # required for rename

    @field_validator('column_name', 'new_column_name')
    @classmethod
    def validate_column_names(cls, v):
        return v if v is None else validate_identifier(v)

    @model_validator(mode='after')
    def check_required_fields(self):
        if self.action in ("add", "modify") and not self.params:
            raise ValueError(f"params is required for action '{self.action}'")
        if self.action == "rename" and not self.new_column_name:
            raise ValueError("new_column_name is required for action 'rename'")
        return self

    model_config = example(database_name="testdb", table_name="users", action="add",
                           column_name="age", params="INT NOT NULL DEFAULT 0")


class TableRenameRequest(DatabaseRequest):
    old_table_name: str
    new_table_name: str

    @field_validator('old_table_name', 'new_table_name')
    @classmethod
    def validate_table_names(cls, v):
        return validate_identifier(v)

    model_config = example(database_name="testdb", old_table_name="users",
                           new_table_name="customers")


# Row request models
class RowValuesRequest(TableRequest):
    values: dict

    @field_validator('values')
    @classmethod
    def validate_values(cls, v):
        if not v:
            raise ValueError("values must not be empty")
        for key in v:
            validate_identifier(key)
        return v


class RowInsertRequest(RowValuesRequest):
    model_config = example(database_name="testdb", table_name="users",
                           values={"username": "john", "email": "john@example.com"})


class RowKeyMixin(BaseModel):
    row_id: int
    key_column: str = "id"

    @field_validator('key_column')
    @classmethod
    def validate_key_column(cls, v):
        return validate_identifier(v)


class RowUpdateRequest(RowKeyMixin, RowValuesRequest):

    model_config = example(database_name="testdb", table_name="users", row_id=1,
                           values={"username": "johnny"})


class RowDeleteRequest(RowKeyMixin, TableRequest):

    model_config = example(database_name="testdb", table_name="users", row_id=1)

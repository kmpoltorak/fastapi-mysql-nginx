from typing import Any, Optional, List
from pydantic import BaseModel, ConfigDict, field_validator
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


class RowUpdateRequest(RowValuesRequest):
    row_id: int

    model_config = example(database_name="testdb", table_name="users", row_id=1,
                           values={"username": "johnny"})


class RowDeleteRequest(TableRequest):
    row_id: int

    model_config = example(database_name="testdb", table_name="users", row_id=1)

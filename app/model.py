from pydantic import BaseModel

################# REQUEST MODELS #################

####### Databaase #######

class DatabaseRequest(BaseModel):
    database_name: str

####### Table #######

class TableColumnField(BaseModel):
    name: str
    params: str

class TableRequest(DatabaseRequest):
    table_name: str

class TableCreateRequest(TableRequest):
    columns: list[TableColumnField]

class TableRenameRequest(DatabaseRequest):
    old_table_name: str
    new_table_name: str

####### Row #######

class RowRequest(TableRequest):
    columns: list
    values: list

class RowCondition(BaseModel):
    column: str
    value: int | float | str

class ConditionRowRequest(RowRequest):
    condition: RowCondition
    
class DeleteRowRequest(TableRequest):
    condition: RowCondition

####### User #######

class UserRequest(BaseModel):
    username: str
    table_name: str
    privileges: dict

################# RESPONSE MODELS #################

class BasicResponse(BaseModel):
    code: int
    message: str

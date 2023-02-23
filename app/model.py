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

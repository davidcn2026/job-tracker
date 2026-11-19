import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginIn(BaseModel):
    name: str = Field(min_length=2, max_length=20)
    password: str = Field(min_length=6, max_length=64)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        # NFKC：全角→半角、合成字符规范化
        # strip：去掉首尾空格
        return unicodedata.normalize("NFKC", v).strip()

class RegisterIn(LoginIn):
    """注册请求：字段约束和登录一致，多一个可选邀请码。"""
    code: str | None = None

class UserOut(BaseModel):
    """响应里的用户：只有 id 和 name。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TokenOut(BaseModel):
    token: str
    user: UserOut
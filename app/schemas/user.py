import unicodedata
from datetime import datetime

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


class ProfileIn(BaseModel):
    """保存简历文本的请求体。

    上限 2 万字：一份简历通常 2~4 千字，2 万足够容纳很长的版本，
    也防止有人把整本书贴进来（会白烧 token）。
    """

    text: str = Field(min_length=1, max_length=20000)

    @field_validator("text")
    @classmethod
    def normalize(cls, v: str) -> str:
        text = v.replace("\r\n", "\n").strip()
        if not text:
            raise ValueError("简历内容不能为空")
        return text


class ProfileOut(BaseModel):
    """当前简历。未上传过时 text 为 None。"""

    text: str | None = None
    updated_at: datetime | None = None
    chars: int = 0


class ProfileImportOut(BaseModel):
    """文件解析结果（**尚未保存**，需要前端确认后再调 PUT 保存）。"""

    text: str
    chars: int
    filename: str | None = None
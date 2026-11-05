from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    login: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.@+-]+$")
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if len(value.encode()) > 72:
            raise ValueError("Пароль не должен превышать 72 байта")
        if not any(char.isupper() for char in value) or not any(char.isdigit() for char in value):
            raise ValueError("Пароль должен содержать заглавную букву и цифру")
        return value


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class TokenRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=8192)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RegisterResponse(BaseModel):
    status: str

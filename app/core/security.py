import hashlib
import secrets

# scrypt 参数：n 越大越慢越安全。2**14 约 40ms，登录场景可接受。
_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


def hash_password(password: str) -> str:
    """生成自描述格式：scrypt$<salt_hex>$<hash_hex>

    带算法名是为了将来换算法（如 argon2）时，老密码仍能按前缀分派校验。
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码。格式异常一律返回 False（不抛异常，避免泄露内部信息）。"""
    try:
        algo, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=_N,
            r=_R,
            p=_P,
            dklen=_DKLEN,
        )
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(dk.hex(), hash_hex)


def generate_token() -> str:
    """43 字符，256 位熵。"""
    return secrets.token_urlsafe(32)

def token_hash(token: str) -> str:
    """token 存库用 sha256（快哈希就够了，因为 token 本身有 256 位熵）。"""
    return hashlib.sha256(token.encode()).hexdigest()
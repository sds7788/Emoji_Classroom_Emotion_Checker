"""Create local secrets once; never overwrite existing configuration or print keys."""

import secrets
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / ".env"
    if destination.exists():
        print(".env 已存在，保留原配置。修改后请重启后端和 AI 服务。")
        return
    template = (root / ".env.example").read_text(encoding="utf-8")
    template = template.replace("replace-with-at-least-32-random-bytes", secrets.token_urlsafe(48))
    template = template.replace("replace-with-a-separate-random-token", secrets.token_urlsafe(48))
    with destination.open("x", encoding="utf-8") as output:
        output.write(template)
    destination.chmod(0o600)
    print("已创建 .env，并生成独立 JWT 签名密钥和 AI 服务令牌；未输出密钥。")
    print("核心功能可直接启动。启用 AI 时在本机编辑 AI_API_KEY、AI_BASE_URL、AI_MODEL。")


if __name__ == "__main__":
    main()

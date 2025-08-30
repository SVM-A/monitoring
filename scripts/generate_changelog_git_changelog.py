import subprocess
import sys
from pathlib import Path

BASE_PATH = Path(__file__).resolve().parent.parent


def generate_changelog(output_path="CHANGELOG.md"):
    result = subprocess.run(
        ["git-changelog", "--output", output_path, "--template", "angular"],
        capture_output=True,
        text=True,
        cwd=BASE_PATH,
    )
    if result.returncode != 0:
        print("Ошибка генерации CHANGELOG:", result.stderr)
        sys.exit(1)
    print(f"✅ CHANGELOG сгенерирован в {output_path}")


def extract_latest_changes(md_path="CHANGELOG.md"):
    lines = (BASE_PATH / md_path).read_text(encoding="utf-8").splitlines()
    changes = []
    inside_block = False
    for line in lines:
        if line.startswith("## "):  # новый релиз
            if inside_block:
                break
            inside_block = True
            changes.append(line)
        elif inside_block and line.strip():
            changes.append(line)
    return "\n".join(changes[:10])


def main():
    generate_changelog()
    latest = extract_latest_changes()
    print("--- Последние изменения ---")
    print(latest)

    lines = latest.splitlines()
    version_line = next((line for line in lines if line.startswith("### ")), "")
    content_lines = [line for line in lines[1:] if line.strip()]
    content = "\n".join(content_lines)

    with open(BASE_PATH / ".version_env", "w", encoding="utf-8") as f:
        f.write(f"LAST_CHANGES_HEADER={version_line.strip()}\n")
        f.write(f"LAST_CHANGES_CONTENT={content.strip().replace(chr(10), '%0A')}")


if __name__ == "__main__":
    main()

"""
tnsnames.ora 파일을 파싱하여 TNS 별칭 목록과 연결 정보를 추출하는 모듈
"""
import os
import re


def find_tnsnames_path() -> str | None:
    """
    tnsnames.ora 파일 위치를 자동으로 탐색합니다.
    우선순위: TNS_ADMIN 환경변수 → ORACLE_HOME → 일반적인 설치 경로
    """
    # 1. TNS_ADMIN 환경변수
    tns_admin = os.environ.get('TNS_ADMIN')
    if tns_admin:
        path = os.path.join(tns_admin, 'tnsnames.ora')
        if os.path.exists(path):
            return path

    # 2. ORACLE_HOME 환경변수
    oracle_home = os.environ.get('ORACLE_HOME')
    if oracle_home:
        path = os.path.join(oracle_home, 'network', 'admin', 'tnsnames.ora')
        if os.path.exists(path):
            return path

    # 3. Windows 일반 설치 경로 탐색
    common_roots = [
        r'C:\oracle',
        r'C:\Oracle',
        r'C:\app',
        r'C:\oraclexe',
    ]

    for root in common_roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if 'tnsnames.ora' in filenames:
                return os.path.join(dirpath, 'tnsnames.ora')

    return None


def parse_tnsnames(filepath: str) -> dict:
    """
    tnsnames.ora 파일을 파싱하여 {별칭: 연결문자열} 딕셔너리를 반환합니다.
    """
    if not filepath or not os.path.exists(filepath):
        return {}

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except OSError:
        return {}

    # 주석 제거 (#으로 시작하는 줄)
    content = re.sub(r'#[^\n]*', '', content)

    entries = {}
    full_text = content

    # 별칭 = 이후 괄호 블록 전체를 추출
    alias_pattern = re.compile(r'^([A-Za-z0-9_.]+)\s*=\s*', re.MULTILINE)

    for match in alias_pattern.finditer(full_text):
        alias = match.group(1).upper()
        start = match.end()

        # 첫 번째 '(' 찾기
        paren_start = full_text.find('(', start)
        if paren_start == -1:
            continue

        # 괄호 균형 맞추기
        depth = 0
        end = paren_start
        for idx in range(paren_start, len(full_text)):
            ch = full_text[idx]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break

        entry_text = full_text[paren_start:end].strip()
        entries[alias] = entry_text

    return entries


def get_alias_list(filepath: str) -> list[str]:
    """TNS 별칭 이름 목록만 반환합니다."""
    entries = parse_tnsnames(filepath)
    return sorted(entries.keys())


def get_connection_string(filepath: str, alias: str) -> str:
    """특정 별칭의 연결 문자열을 반환합니다."""
    entries = parse_tnsnames(filepath)
    return entries.get(alias.upper(), '')


if __name__ == '__main__':
    path = find_tnsnames_path()
    print(f'tnsnames.ora 위치: {path}')
    if path:
        aliases = get_alias_list(path)
        print(f'발견된 TNS 별칭: {aliases}')

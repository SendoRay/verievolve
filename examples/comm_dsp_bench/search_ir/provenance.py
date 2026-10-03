"""历史实验源码的字节级溯源；不执行旧代码，也不放松当前运行的漂移检查。"""

import hashlib
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_CHECKPOINT = "834d449"


class ProvenanceError(RuntimeError):
    pass


def verify_source_record(record, *, root=ROOT, checkpoint=ARCHIVE_CHECKPOINT):
    """当前文件或指定Git检查点必须逐字节匹配原实验所记SHA-256。

    检查点是源码存档，不声称该提交在早期实验运行时已经存在。
    缓存消费者仍须另外核验当前RTL、工具、库和脚本身份。
    """
    path = Path(record["path"])
    expected = record["sha256"]
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ProvenanceError("非法源码摘要")
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
        return {"path": str(path), "sha256": expected, "verified_via": "current-file"}
    if not re.fullmatch(r"[0-9a-f]{7,40}", checkpoint):
        raise ProvenanceError("源码存档必须是明确的Git提交ID")
    try:
        relative = path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError as exc:
        raise ProvenanceError("变化的历史源码不在已知仓库内") from exc
    result = subprocess.run(["git", "show", f"{checkpoint}:{relative}"], cwd=root,
                            capture_output=True, timeout=30)
    if result.returncode or hashlib.sha256(result.stdout).hexdigest() != expected:
        raise ProvenanceError(f"历史源码无法由当前文件或Git存档验证: {relative}")
    return {"path": str(path), "sha256": expected, "verified_via": f"git:{checkpoint}:{relative}"}

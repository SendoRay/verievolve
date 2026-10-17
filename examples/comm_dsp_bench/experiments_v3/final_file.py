"""对一个原语程序文件做 verdict.final，结果写 JSON。用法：python final_file.py 任务 程序.py 输出.json"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dspgen.verdict import final
r = final(Path(sys.argv[2]).read_text(), sys.argv[1], Path(sys.argv[2]))
Path(sys.argv[3]).write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
print(r["verdict"], r.get("reject_reasons"), r.get("objectives"))

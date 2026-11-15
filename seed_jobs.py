"""一次性种子数据：插入 10 条投递记录。

用法：python seed_jobs.py
注意：user_id 先固定为 1（users 表和外键还没做）。
"""

import asyncio
from datetime import date

from app.db.session import AsyncSessionLocal, engine
from app.models.job import Job

ROWS = [
    dict(
        company="星辰科技", position="Python 后端开发实习生", status="已投",
        salary_min=15, salary_max=25, salary_note="13薪",
        source="Boss直聘", url="https://example.com/job/1001",
        published_at=date(2026, 10, 8),
        description="岗位职责：负责内部平台后端接口开发；任职要求：熟悉 Python、FastAPI、MySQL，有项目经验优先。",
        company_business="企业级 SaaS", note="HR 说一周内安排笔试",
    ),
    dict(
        company="云图信息", position="AI 应用开发实习生", status="面试中",
        salary_min=12, salary_max=20,
        source="本校", source_detail="校招宣讲会",
        url="https://example.com/job/1002",
        published_at=date(2026, 10, 10),
        description="负责 LLM 应用落地，包括 RAG 检索、提示词工程、评测。要求熟悉 Python，了解向量库。",
        company_business="行业大模型解决方案", note="一面已过，二面等下周三通知",
    ),
    dict(
        company="蓝鲸数据", position="后端开发工程师（校招）", status="待投",
        salary_min=18, salary_max=30, salary_note="含绩效",
        source="Boss直聘", url="https://example.com/job/1003",
        published_at=date(2026, 10, 5),
        description="负责数据平台后端服务开发，要求掌握 Python/Java 其一，熟悉 MySQL、Redis、Docker。",
        company_business="数据中台与 BI", note="要求 Docker，正好在补",
    ),
    dict(
        company="极光软件", position="Python 开发实习生", status="已面试",
        salary_min=10, salary_max=15,
        source="自定义", source_detail="师兄内推",
        published_at=date(2026, 9, 28),
        description="参与内部工具开发，脚本与自动化为主。要求 Python 基础扎实，会用 Linux 命令行。",
        company_business="政企信息化", note="面试问到 SQL 索引，答得不完整",
    ),
    dict(
        company="沧澜网络", position="服务端开发实习生", status="已投",
        salary_min=16, salary_max=24, salary_note="13薪",
        source="Boss直聘", url="https://example.com/job/1005",
        published_at=date(2026, 10, 12),
        description="负责游戏服务端接口开发，要求熟悉 Python 或 Go，了解并发与网络编程。",
        company_business="游戏研发", note="",
    ),
    dict(
        company="远山智能", position="算法工程师实习生", status="已挂",
        salary_min=20, salary_max=35,
        source="其他", source_detail="招聘公众号",
        published_at=date(2026, 9, 20),
        description="偏 CV 方向，要求 PyTorch、论文阅读能力，有比赛经历优先。",
        company_business="计算机视觉", note="方向不匹配，笔试未过",
    ),
    dict(
        company="青柚科技", position="数据平台开发实习生", status="待投",
        salary_min=16, salary_max=24,
        source="Boss直聘", url="https://example.com/job/1007",
        published_at=date(2026, 10, 15),
        description="负责数据采集与清洗流程开发，要求 Python + SQL 熟练，了解调度工具。",
        company_business="电商数据分析", note="JD 里没写学历要求，可以试试",
    ),
    dict(
        company="简行科技", position="Python 后端开发", status="面试中",
        salary_min=15, salary_max=25, salary_note="试用期八折",
        source="本校", source_detail="学院就业群",
        published_at=date(2026, 10, 2),
        description="维护订单与结算服务，要求熟悉 MySQL 事务、索引优化，会写单元测试。",
        company_business="出行服务", note="二面要现场写 SQL，需要准备",
    ),
    dict(
        company="明河信息", position="Python 服务端工程师", status="已投",
        salary_min=18, salary_max=28,
        source="自定义", source_detail="官网投递",
        url="https://example.com/job/1009",
        published_at=date(2026, 10, 9),
        description="负责 SaaS 产品后端模块开发，技术栈 FastAPI + PostgreSQL + Redis。",
        company_business="协同办公 SaaS", note="",
    ),
    dict(
        company="南风软件", position="Python 开发实习生", status="已面试",
        salary_min=8, salary_max=12,
        source="本校", source_detail="校园双选会",
        published_at=date(2026, 10, 18),
        description="参与管理系统开发，主要写后端接口与报表导出。",
        company_business="政务软件", note="薪资偏低，作为保底",
    ),
]


async def main() -> None:
    try:
        async with AsyncSessionLocal() as db:
            db.add_all([Job(user_id=1, **row) for row in ROWS])
            await db.commit()
        print(f"插入完成：{len(ROWS)} 条")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

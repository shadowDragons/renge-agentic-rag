from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import hash_password, verify_password
from app.db.base import Base
from app.db.init_db import seed_defaults
from app.models import Assistant, AuthUser, KnowledgeBase


def _build_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_seed_defaults_skips_demo_users_outside_dev_and_test() -> None:
    with _build_session() as db:
        seed_defaults(db, app_env="prod")

        users = db.scalars(select(AuthUser)).all()
        knowledge_bases = db.scalars(select(KnowledgeBase)).all()
        assistants = db.scalars(select(Assistant)).all()

    assert users == []
    assert len(knowledge_bases) == 1
    assert len(assistants) == 1


def test_seed_defaults_does_not_reset_existing_demo_user_password() -> None:
    custom_password = "custom-password-001"
    with _build_session() as db:
        db.add(
            AuthUser(
                user_id="user-admin-001",
                username="admin",
                display_name="自定义管理员",
                password_hash=hash_password(custom_password),
                roles=["admin"],
                is_active=True,
            )
        )
        db.commit()

        seed_defaults(db, app_env="dev")

        admin = db.scalar(select(AuthUser).where(AuthUser.username == "admin"))

    assert admin is not None
    assert admin.display_name == "自定义管理员"
    assert verify_password(custom_password, admin.password_hash)


def test_seed_defaults_does_not_overwrite_existing_demo_assistant() -> None:
    with _build_session() as db:
        db.add(
            KnowledgeBase(
                knowledge_base_id="kb-demo-001",
                knowledge_base_name="自定义知识库",
                description="手工配置知识库",
                default_retrieval_top_k=9,
            )
        )
        db.add(
            Assistant(
                assistant_id="asst-demo-001",
                assistant_name="自定义助理",
                description="手工配置助理",
                system_prompt="请按自定义配置回答。",
                default_model="custom-model",
                default_kb_ids=["kb-demo-001"],
                tool_keys=["tool-1"],
                review_rules=[],
                review_enabled=True,
                version=7,
            )
        )
        db.commit()

        seed_defaults(db, app_env="dev")

        assistant = db.scalar(
            select(Assistant).where(Assistant.assistant_id == "asst-demo-001")
        )
        knowledge_base = db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.knowledge_base_id == "kb-demo-001"
            )
        )

    assert assistant is not None
    assert assistant.assistant_name == "自定义助理"
    assert assistant.default_model == "custom-model"
    assert assistant.review_enabled is True
    assert assistant.version == 7
    assert knowledge_base is not None
    assert knowledge_base.knowledge_base_name == "自定义知识库"
    assert knowledge_base.default_retrieval_top_k == 9

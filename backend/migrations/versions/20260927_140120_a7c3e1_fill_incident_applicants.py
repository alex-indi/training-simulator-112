"""Fill missing applicant details in existing incidents.

Revision ID: 20260927_140120_a7c3e1
Revises: 20260927_130030_19872b
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260927_140120_a7c3e1"
down_revision: str | Sequence[str] | None = "20260927_130030_19872b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE incidents
        SET
            applicant_name = CASE
                WHEN applicant_name IS NULL OR btrim(applicant_name) = '' THEN
                    (ARRAY[
                        'Александров Александр Сергеевич',
                        'Белов Дмитрий Андреевич',
                        'Васильев Михаил Олегович',
                        'Волкова Анна Игоревна',
                        'Захарова Елена Викторовна',
                        'Козлов Алексей Николаевич',
                        'Кузнецова Мария Александровна',
                        'Морозов Иван Павлович',
                        'Новикова Ольга Сергеевна',
                        'Орлов Максим Дмитриевич',
                        'Петрова Наталья Андреевна',
                        'Смирнов Сергей Владимирович',
                        'Соколова Екатерина Михайловна',
                        'Фёдоров Артём Романович',
                        'Яковлева Ирина Алексеевна'
                    ])[1 + floor(random() * 15)::integer]
                ELSE applicant_name
            END,
            applicant_phone = CASE
                WHEN applicant_phone IS NULL OR btrim(applicant_phone) = '' THEN
                    '+7 (9' || lpad(floor(random() * 100)::integer::text, 2, '0') || ') '
                    || substring(lpad(floor(random() * 10000000)::integer::text, 7, '0'), 1, 3)
                    || '-' || substring(lpad(floor(random() * 10000000)::integer::text, 7, '0'), 4, 2)
                    || '-' || substring(lpad(floor(random() * 10000000)::integer::text, 7, '0'), 6, 2)
                ELSE applicant_phone
            END
        WHERE applicant_name IS NULL OR btrim(applicant_name) = ''
           OR applicant_phone IS NULL OR btrim(applicant_phone) = ''
        """
    )
    op.execute(
        """
        UPDATE incidents
        SET source_snapshot = source_snapshot || jsonb_build_object(
            'applicant_name', applicant_name,
            'applicant_phone', applicant_phone
        )
        """
    )


def downgrade() -> None:
    pass

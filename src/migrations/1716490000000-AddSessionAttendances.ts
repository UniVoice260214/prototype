import { MigrationInterface, QueryRunner } from 'typeorm';

/**
 * 학생 세션 참여 기록. 지난 수업 자막 열람 권한 검증과
 * 학생용 "내 수업 목록"의 근거 데이터다.
 */
export class AddSessionAttendances1716490000000 implements MigrationInterface {
  name = 'AddSessionAttendances1716490000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`
      CREATE TABLE "session_attendances" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "studentId" uuid NOT NULL,
        "sessionId" uuid NOT NULL,
        "locale" varchar(16) NOT NULL,
        "joinedAt" TIMESTAMPTZ NOT NULL,
        "createdAt" TIMESTAMP NOT NULL DEFAULT now(),
        "updatedAt" TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT "PK_session_attendances" PRIMARY KEY ("id"),
        CONSTRAINT "UQ_session_attendances_student_session"
          UNIQUE ("studentId", "sessionId"),
        CONSTRAINT "FK_session_attendances_student" FOREIGN KEY ("studentId")
          REFERENCES "students"("id") ON DELETE CASCADE,
        CONSTRAINT "FK_session_attendances_session" FOREIGN KEY ("sessionId")
          REFERENCES "sessions"("id") ON DELETE CASCADE
      )
    `);
    await queryRunner.query(`
      CREATE INDEX "IDX_session_attendances_student"
        ON "session_attendances" ("studentId")
    `);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`DROP INDEX "IDX_session_attendances_student"`);
    await queryRunner.query(`DROP TABLE "session_attendances"`);
  }
}

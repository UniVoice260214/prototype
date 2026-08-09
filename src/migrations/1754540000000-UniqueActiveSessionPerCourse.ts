import { MigrationInterface, QueryRunner } from 'typeorm';

/**
 * Prevents two sessions from being 'active' for the same course at once.
 *
 * SessionService.start() already checks for an existing active session
 * before inserting, but that check-then-insert is not atomic: two concurrent
 * "수업 시작" requests (double click, two tabs, a client retry) can both pass
 * the check and both insert. A partial unique index enforces the invariant
 * at the database level regardless of application-level races.
 */
export class UniqueActiveSessionPerCourse1754540000000
  implements MigrationInterface
{
  name = 'UniqueActiveSessionPerCourse1754540000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`
      CREATE UNIQUE INDEX "UQ_sessions_active_per_course"
      ON "sessions" ("courseId")
      WHERE "status" = 'active'
    `);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `DROP INDEX IF EXISTS "UQ_sessions_active_per_course"`,
    );
  }
}

import { MigrationInterface, QueryRunner } from 'typeorm';

/**
 * 과목 전공(ai | hss | bme). 수업 시작 시 워커에 전달되어 그 전공의 RAG 인덱스만
 * 검색하게 한다. null 은 "미지정" — 워커가 RAG_DEFAULT_MAJOR 로 폴백한다.
 */
export class AddCourseMajor1716510000000 implements MigrationInterface {
  name = 'AddCourseMajor1716510000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`ALTER TABLE "courses" ADD "major" varchar(16)`);
    await queryRunner.query(`
      ALTER TABLE "courses" ADD CONSTRAINT "CHK_courses_major"
        CHECK ("major" IS NULL OR "major" IN ('ai', 'hss', 'bme'))
    `);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`ALTER TABLE "courses" DROP CONSTRAINT "CHK_courses_major"`);
    await queryRunner.query(`ALTER TABLE "courses" DROP COLUMN "major"`);
  }
}

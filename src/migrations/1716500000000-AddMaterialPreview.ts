import { MigrationInterface, QueryRunner } from 'typeorm';

/**
 * 학생 화면용 자료 미리보기(PDF). PDF 원본은 그대로, PPT/PPTX 는 업로드 후
 * 변환된 PDF 를 previewBlobUrl 에 둔다. 기존 PPT 자료는 변환 이력이 없으므로
 * failed 로 두고 재업로드를 유도한다.
 */
export class AddMaterialPreview1716500000000 implements MigrationInterface {
  name = 'AddMaterialPreview1716500000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `CREATE TYPE "materials_previewstatus_enum" AS ENUM ('pending', 'ready', 'failed')`,
    );
    await queryRunner.query(
      `ALTER TABLE "materials" ADD "previewBlobUrl" text`,
    );
    await queryRunner.query(
      `ALTER TABLE "materials" ADD "previewStatus" "materials_previewstatus_enum" NOT NULL DEFAULT 'pending'`,
    );
    await queryRunner.query(`
      UPDATE "materials"
      SET "previewBlobUrl" = "blobUrl", "previewStatus" = 'ready'
      WHERE lower("originalFilename") LIKE '%.pdf'
    `);
    await queryRunner.query(`
      UPDATE "materials" SET "previewStatus" = 'failed'
      WHERE "previewBlobUrl" IS NULL
    `);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `ALTER TABLE "materials" DROP COLUMN "previewStatus"`,
    );
    await queryRunner.query(
      `ALTER TABLE "materials" DROP COLUMN "previewBlobUrl"`,
    );
    await queryRunner.query(`DROP TYPE "materials_previewstatus_enum"`);
  }
}

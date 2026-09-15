import { MigrationInterface, QueryRunner } from 'typeorm';

/**
 * 자막 저장 기능: 워커가 발행한 확정 자막 세그먼트를 세션별로 보관한다.
 * 수업 후 이력 조회(스크롤백)와 QA 회귀 분석에 쓰인다.
 */
export class AddTranscriptSegments1716480000000 implements MigrationInterface {
  name = 'AddTranscriptSegments1716480000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`
      CREATE TABLE "transcript_segments" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "sessionId" uuid NOT NULL,
        "segmentId" varchar(120) NOT NULL,
        "sequence" int NOT NULL,
        "textKo" text NOT NULL,
        "rawTextKo" text,
        "sttConfidence" real,
        "translations" jsonb NOT NULL DEFAULT '{}'::jsonb,
        "createdAt" TIMESTAMP NOT NULL DEFAULT now(),
        "updatedAt" TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT "PK_transcript_segments" PRIMARY KEY ("id"),
        CONSTRAINT "UQ_transcript_segments_segmentId" UNIQUE ("segmentId"),
        CONSTRAINT "FK_transcript_segments_session" FOREIGN KEY ("sessionId")
          REFERENCES "sessions"("id") ON DELETE CASCADE
      )
    `);
    await queryRunner.query(`
      CREATE INDEX "IDX_transcript_segments_session_sequence"
        ON "transcript_segments" ("sessionId", "sequence")
    `);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `DROP INDEX "IDX_transcript_segments_session_sequence"`,
    );
    await queryRunner.query(`DROP TABLE "transcript_segments"`);
  }
}

import { MigrationInterface, QueryRunner } from 'typeorm';

/**
 * Initial schema matching the project database design.
 * Assumes PostgreSQL 13+ with pgcrypto available.
 */
export class InitSchema1716470000000 implements MigrationInterface {
  name = 'InitSchema1716470000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`CREATE EXTENSION IF NOT EXISTS "pgcrypto"`);

    // Enums
    await queryRunner.query(
      `CREATE TYPE "users_role_enum" AS ENUM ('admin', 'professor')`,
    );
    await queryRunner.query(
      `CREATE TYPE "sessions_status_enum" AS ENUM ('active', 'ended')`,
    );
    await queryRunner.query(
      `CREATE TYPE "materials_sourcetype_enum" AS ENUM ('lecture', 'major')`,
    );
    await queryRunner.query(
      `CREATE TYPE "materials_indexingstatus_enum" AS ENUM ('pending', 'processing', 'done', 'failed')`,
    );

    // users
    await queryRunner.query(`
      CREATE TABLE "users" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "email" varchar(255) NOT NULL,
        "passwordHash" varchar(255) NOT NULL,
        "name" varchar(100) NOT NULL,
        "role" "users_role_enum" NOT NULL,
        "createdAt" TIMESTAMP NOT NULL DEFAULT now(),
        "updatedAt" TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT "PK_users" PRIMARY KEY ("id"),
        CONSTRAINT "UQ_users_email" UNIQUE ("email")
      )
    `);

    // students
    await queryRunner.query(`
      CREATE TABLE "students" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "email" varchar(255) NOT NULL,
        "passwordHash" varchar(255) NOT NULL,
        "name" varchar(100) NOT NULL,
        "preferredLocale" varchar(16),
        "createdAt" TIMESTAMP NOT NULL DEFAULT now(),
        "updatedAt" TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT "PK_students" PRIMARY KEY ("id"),
        CONSTRAINT "UQ_students_email" UNIQUE ("email")
      )
    `);

    // schools
    await queryRunner.query(`
      CREATE TABLE "schools" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "name" varchar(200) NOT NULL,
        "createdAt" TIMESTAMP NOT NULL DEFAULT now(),
        "updatedAt" TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT "PK_schools" PRIMARY KEY ("id")
      )
    `);

    // departments
    await queryRunner.query(`
      CREATE TABLE "departments" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "name" varchar(200) NOT NULL,
        "schoolId" uuid NOT NULL,
        "createdAt" TIMESTAMP NOT NULL DEFAULT now(),
        "updatedAt" TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT "PK_departments" PRIMARY KEY ("id"),
        CONSTRAINT "FK_departments_school" FOREIGN KEY ("schoolId")
          REFERENCES "schools"("id") ON DELETE RESTRICT
      )
    `);

    // professors
    await queryRunner.query(`
      CREATE TABLE "professors" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "userId" uuid NOT NULL,
        "departmentId" uuid NOT NULL,
        "createdAt" TIMESTAMP NOT NULL DEFAULT now(),
        "updatedAt" TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT "PK_professors" PRIMARY KEY ("id"),
        CONSTRAINT "UQ_professors_userId" UNIQUE ("userId"),
        CONSTRAINT "FK_professors_user" FOREIGN KEY ("userId")
          REFERENCES "users"("id") ON DELETE CASCADE,
        CONSTRAINT "FK_professors_department" FOREIGN KEY ("departmentId")
          REFERENCES "departments"("id") ON DELETE RESTRICT
      )
    `);

    // courses
    await queryRunner.query(`
      CREATE TABLE "courses" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "name" varchar(200) NOT NULL,
        "departmentId" uuid NOT NULL,
        "professorId" uuid NOT NULL,
        "createdAt" TIMESTAMP NOT NULL DEFAULT now(),
        "updatedAt" TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT "PK_courses" PRIMARY KEY ("id"),
        CONSTRAINT "FK_courses_department" FOREIGN KEY ("departmentId")
          REFERENCES "departments"("id") ON DELETE RESTRICT,
        CONSTRAINT "FK_courses_professor" FOREIGN KEY ("professorId")
          REFERENCES "professors"("id") ON DELETE RESTRICT
      )
    `);

    // sessions
    await queryRunner.query(`
      CREATE TABLE "sessions" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "courseId" uuid NOT NULL,
        "liveKitRoomName" varchar(200) NOT NULL,
        "status" "sessions_status_enum" NOT NULL DEFAULT 'active',
        "targetLocales" text[] NOT NULL DEFAULT ARRAY[]::text[],
        "startedAt" TIMESTAMPTZ NOT NULL,
        "endedAt" TIMESTAMPTZ,
        "createdAt" TIMESTAMP NOT NULL DEFAULT now(),
        "updatedAt" TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT "PK_sessions" PRIMARY KEY ("id"),
        CONSTRAINT "UQ_sessions_liveKitRoomName" UNIQUE ("liveKitRoomName"),
        CONSTRAINT "FK_sessions_course" FOREIGN KEY ("courseId")
          REFERENCES "courses"("id") ON DELETE RESTRICT
      )
    `);

    // materials
    await queryRunner.query(`
      CREATE TABLE "materials" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "sessionId" uuid,
        "courseId" uuid NOT NULL,
        "blobUrl" text NOT NULL,
        "originalFilename" varchar(500) NOT NULL,
        "sourceType" "materials_sourcetype_enum" NOT NULL,
        "week" int,
        "indexingStatus" "materials_indexingstatus_enum" NOT NULL DEFAULT 'pending',
        "createdAt" TIMESTAMP NOT NULL DEFAULT now(),
        "updatedAt" TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT "PK_materials" PRIMARY KEY ("id"),
        CONSTRAINT "FK_materials_session" FOREIGN KEY ("sessionId")
          REFERENCES "sessions"("id") ON DELETE SET NULL,
        CONSTRAINT "FK_materials_course" FOREIGN KEY ("courseId")
          REFERENCES "courses"("id") ON DELETE RESTRICT
      )
    `);

    // glossaries
    await queryRunner.query(`
      CREATE TABLE "glossaries" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "courseId" uuid NOT NULL,
        "term" varchar(200) NOT NULL,
        "pronunciation" varchar(200),
        "definition" text,
        "translations" jsonb NOT NULL DEFAULT '{}'::jsonb,
        "createdAt" TIMESTAMP NOT NULL DEFAULT now(),
        "updatedAt" TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT "PK_glossaries" PRIMARY KEY ("id"),
        CONSTRAINT "UQ_glossaries_courseId_term" UNIQUE ("courseId", "term"),
        CONSTRAINT "FK_glossaries_course" FOREIGN KEY ("courseId")
          REFERENCES "courses"("id") ON DELETE CASCADE
      )
    `);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`DROP TABLE IF EXISTS "glossaries"`);
    await queryRunner.query(`DROP TABLE IF EXISTS "materials"`);
    await queryRunner.query(`DROP TABLE IF EXISTS "sessions"`);
    await queryRunner.query(`DROP TABLE IF EXISTS "courses"`);
    await queryRunner.query(`DROP TABLE IF EXISTS "professors"`);
    await queryRunner.query(`DROP TABLE IF EXISTS "departments"`);
    await queryRunner.query(`DROP TABLE IF EXISTS "schools"`);
    await queryRunner.query(`DROP TABLE IF EXISTS "students"`);
    await queryRunner.query(`DROP TABLE IF EXISTS "users"`);
    await queryRunner.query(
      `DROP TYPE IF EXISTS "materials_indexingstatus_enum"`,
    );
    await queryRunner.query(`DROP TYPE IF EXISTS "materials_sourcetype_enum"`);
    await queryRunner.query(`DROP TYPE IF EXISTS "sessions_status_enum"`);
    await queryRunner.query(`DROP TYPE IF EXISTS "users_role_enum"`);
  }
}

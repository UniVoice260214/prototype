import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { Course } from '../../modules/course/entities/course.entity';
import { Glossary } from '../../modules/glossary/entities/glossary.entity';
import { Material } from '../../modules/material/entities/material.entity';
import { Professor } from '../../modules/professor/entities/professor.entity';
import { Session } from '../../modules/session/entities/session.entity';
import { SessionAttendance } from '../../modules/session/entities/session-attendance.entity';
import { AuthModule } from '../../modules/auth/auth.module';
import { CourseAccessService } from './course-access.service';
import { StudentSessionAccessService } from './student-session-access.service';

@Module({
  imports: [
    TypeOrmModule.forFeature([
      Course,
      Glossary,
      Material,
      Professor,
      Session,
      SessionAttendance,
    ]),
    AuthModule,
  ],
  providers: [CourseAccessService, StudentSessionAccessService],
  exports: [CourseAccessService, StudentSessionAccessService],
})
export class CourseAccessModule {}

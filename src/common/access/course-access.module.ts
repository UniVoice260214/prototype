import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { Course } from '../../modules/course/entities/course.entity';
import { Professor } from '../../modules/professor/entities/professor.entity';
import { Session } from '../../modules/session/entities/session.entity';
import { CourseAccessService } from './course-access.service';

@Module({
  imports: [TypeOrmModule.forFeature([Course, Professor, Session])],
  providers: [CourseAccessService],
  exports: [CourseAccessService],
})
export class CourseAccessModule {}

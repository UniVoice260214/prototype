import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { CourseAccessModule } from '../../common/access/course-access.module';
import { Course } from './entities/course.entity';
import { CourseController } from './course.controller';
import { CourseService } from './course.service';

@Module({
  imports: [TypeOrmModule.forFeature([Course]), CourseAccessModule],
  controllers: [CourseController],
  providers: [CourseService],
  exports: [CourseService],
})
export class CourseModule {}

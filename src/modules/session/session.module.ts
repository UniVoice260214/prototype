import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { Course } from '../course/entities/course.entity';
import { Glossary } from '../glossary/entities/glossary.entity';
import { AuthModule } from '../auth/auth.module';
import { CourseAccessModule } from '../../common/access/course-access.module';
import { Session } from './entities/session.entity';
import { SessionAttendance } from './entities/session-attendance.entity';
import { SessionController } from './session.controller';
import { SessionService } from './session.service';

@Module({
  imports: [
    TypeOrmModule.forFeature([Session, SessionAttendance, Course, Glossary]),
    AuthModule,
    CourseAccessModule,
  ],
  controllers: [SessionController],
  providers: [SessionService],
  exports: [SessionService],
})
export class SessionModule {}

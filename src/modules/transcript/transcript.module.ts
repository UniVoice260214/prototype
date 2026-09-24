import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { CourseAccessModule } from '../../common/access/course-access.module';
import { AuthModule } from '../auth/auth.module';
import { Session } from '../session/entities/session.entity';
import { SessionAttendance } from '../session/entities/session-attendance.entity';
import { TranscriptSegment } from './entities/transcript-segment.entity';
import { TranscriptController } from './transcript.controller';
import { TranscriptService } from './transcript.service';
import { TranscriptSubscriber } from './transcript.subscriber';

@Module({
  imports: [
    TypeOrmModule.forFeature([TranscriptSegment, Session, SessionAttendance]),
    AuthModule,
    CourseAccessModule,
  ],
  controllers: [TranscriptController],
  providers: [TranscriptService, TranscriptSubscriber],
  exports: [TranscriptService],
})
export class TranscriptModule {}

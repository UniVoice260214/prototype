import { Module } from '@nestjs/common';
import { CourseAccessModule } from '../../common/access/course-access.module';
import { AuthModule } from '../auth/auth.module';
import { QrController } from './qr.controller';
import { QrService } from './qr.service';

@Module({
  imports: [AuthModule, CourseAccessModule],
  controllers: [QrController],
  providers: [QrService],
})
export class QrModule {}

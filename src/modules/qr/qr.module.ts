import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { AuthModule } from '../auth/auth.module';
import { Session } from '../session/entities/session.entity';
import { QrController } from './qr.controller';
import { QrService } from './qr.service';

@Module({
  imports: [TypeOrmModule.forFeature([Session]), AuthModule],
  controllers: [QrController],
  providers: [QrService],
})
export class QrModule {}

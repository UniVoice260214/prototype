import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { CourseAccessModule } from '../../common/access/course-access.module';
import { Session } from '../session/entities/session.entity';
import { Material } from './entities/material.entity';
import { MaterialController } from './material.controller';
import { MaterialIndexingSubscriber } from './material-indexing.subscriber';
import { MaterialPreviewService } from './material-preview.service';
import { MaterialService } from './material.service';
import { StudentMaterialController } from './student-material.controller';

@Module({
  imports: [TypeOrmModule.forFeature([Material, Session]), CourseAccessModule],
  controllers: [MaterialController, StudentMaterialController],
  providers: [
    MaterialService,
    MaterialPreviewService,
    MaterialIndexingSubscriber,
  ],
  exports: [MaterialService],
})
export class MaterialModule {}

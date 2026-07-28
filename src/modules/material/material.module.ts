import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { CourseAccessModule } from '../../common/access/course-access.module';
import { Material } from './entities/material.entity';
import { MaterialController } from './material.controller';
import { MaterialIndexingSubscriber } from './material-indexing.subscriber';
import { MaterialService } from './material.service';

@Module({
  imports: [TypeOrmModule.forFeature([Material]), CourseAccessModule],
  controllers: [MaterialController],
  providers: [MaterialService, MaterialIndexingSubscriber],
  exports: [MaterialService],
})
export class MaterialModule {}

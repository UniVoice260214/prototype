import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { Material } from './entities/material.entity';
import { MaterialController } from './material.controller';
import { MaterialIndexingSubscriber } from './material-indexing.subscriber';
import { MaterialService } from './material.service';

@Module({
  imports: [TypeOrmModule.forFeature([Material])],
  controllers: [MaterialController],
  providers: [MaterialService, MaterialIndexingSubscriber],
  exports: [MaterialService],
})
export class MaterialModule {}

import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { CourseAccessModule } from '../../common/access/course-access.module';
import { Glossary } from './entities/glossary.entity';
import { GlossaryController } from './glossary.controller';
import { GlossaryService } from './glossary.service';

@Module({
  imports: [TypeOrmModule.forFeature([Glossary]), CourseAccessModule],
  controllers: [GlossaryController],
  providers: [GlossaryService],
  exports: [GlossaryService],
})
export class GlossaryModule {}

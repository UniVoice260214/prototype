import { Inject, Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import type Redis from 'ioredis';
import { Repository } from 'typeorm';
import { CourseAccessService } from '../../common/access/course-access.service';
import { AuthUser } from '../../common/decorators/current-user.decorator';
import { RedisKeys } from '../../common/redis-keys';
import { REDIS_CLIENT } from '../../infra/redis/redis.module';
import { Glossary } from './entities/glossary.entity';
import { CreateGlossaryDto, UpdateGlossaryDto } from './dto/glossary.dto';

@Injectable()
export class GlossaryService {
  constructor(
    @InjectRepository(Glossary) private readonly repo: Repository<Glossary>,
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
    private readonly courseAccess: CourseAccessService,
  ) {}

  async create(dto: CreateGlossaryDto, user: AuthUser): Promise<Glossary> {
    await this.courseAccess.findCourseForUser(dto.courseId, user);
    const saved = await this.repo.save(
      this.repo.create({
        courseId: dto.courseId,
        term: dto.term,
        pronunciation: dto.pronunciation ?? null,
        definition: dto.definition ?? null,
        translations: dto.translations ?? {},
      }),
    );
    await this.invalidateCache(dto.courseId);
    return saved;
  }

  findAll(filters: { courseId?: string }, user: AuthUser): Promise<Glossary[]> {
    return this.courseAccess.findGlossariesForUser(filters, user);
  }

  findOne(id: string, user: AuthUser): Promise<Glossary> {
    return this.courseAccess.findGlossaryForUser(id, user);
  }

  async update(
    id: string,
    dto: UpdateGlossaryDto,
    user: AuthUser,
  ): Promise<Glossary> {
    const glossary = await this.findOne(id, user);
    Object.assign(glossary, {
      term: dto.term ?? glossary.term,
      pronunciation: dto.pronunciation ?? glossary.pronunciation,
      definition: dto.definition ?? glossary.definition,
      translations: dto.translations ?? glossary.translations,
    });
    const saved = await this.repo.save(glossary);
    await this.invalidateCache(glossary.courseId);
    return saved;
  }

  async remove(id: string, user: AuthUser): Promise<void> {
    const glossary = await this.findOne(id, user);
    await this.repo.delete(id);
    await this.invalidateCache(glossary.courseId);
  }

  // Active sessions keep their current preload until the next refresh cycle.
  private async invalidateCache(courseId: string): Promise<void> {
    await this.redis.del(RedisKeys.glossaryByCourse(courseId));
  }
}

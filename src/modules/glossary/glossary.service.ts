import {
  Inject,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import type Redis from 'ioredis';
import { Repository } from 'typeorm';
import { REDIS_CLIENT } from '../../infra/redis/redis.module';
import { Glossary } from './entities/glossary.entity';
import {
  CreateGlossaryDto,
  UpdateGlossaryDto,
} from './dto/glossary.dto';

@Injectable()
export class GlossaryService {
  constructor(
    @InjectRepository(Glossary) private readonly repo: Repository<Glossary>,
    @Inject(REDIS_CLIENT) private readonly redis: Redis,
  ) {}

  async create(dto: CreateGlossaryDto): Promise<Glossary> {
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

  findAll(courseId?: string): Promise<Glossary[]> {
    return this.repo.find({ where: courseId ? { courseId } : {} });
  }

  async findOne(id: string): Promise<Glossary> {
    const g = await this.repo.findOne({ where: { id } });
    if (!g) throw new NotFoundException(`Glossary ${id} not found`);
    return g;
  }

  async update(id: string, dto: UpdateGlossaryDto): Promise<Glossary> {
    const g = await this.findOne(id);
    Object.assign(g, {
      term: dto.term ?? g.term,
      pronunciation: dto.pronunciation ?? g.pronunciation,
      definition: dto.definition ?? g.definition,
      translations: dto.translations ?? g.translations,
    });
    const saved = await this.repo.save(g);
    await this.invalidateCache(g.courseId);
    return saved;
  }

  async remove(id: string): Promise<void> {
    const g = await this.findOne(id);
    await this.repo.delete(id);
    await this.invalidateCache(g.courseId);
  }

  /**
   * 진행 중 세션이 있더라도 다음 세션 시작 시 prewarm 재실행되므로
   * 보수적으로 cache 키만 삭제. (활성 세션은 변경분이 즉시 반영되지 않을 수 있음 — 문서화 사항.)
   */
  private async invalidateCache(courseId: string): Promise<void> {
    await this.redis.del(`glossary:${courseId}`);
  }
}

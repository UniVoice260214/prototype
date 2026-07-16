import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { Course } from './entities/course.entity';
import { CreateCourseDto, UpdateCourseDto } from './dto/course.dto';

@Injectable()
export class CourseService {
  constructor(
    @InjectRepository(Course) private readonly repo: Repository<Course>,
  ) {}

  create(dto: CreateCourseDto) {
    return this.repo.save(this.repo.create(dto));
  }

  findAll(opts: { departmentId?: string; professorId?: string }) {
    const where = Object.fromEntries(
      Object.entries(opts).filter(([, value]) => value !== undefined),
    );
    return this.repo.find({ where });
  }

  async findOne(id: string) {
    const c = await this.repo.findOne({ where: { id } });
    if (!c) throw new NotFoundException(`Course ${id} not found`);
    return c;
  }

  async update(id: string, dto: UpdateCourseDto) {
    const c = await this.findOne(id);
    Object.assign(c, dto);
    return this.repo.save(c);
  }

  async remove(id: string) {
    const res = await this.repo.delete(id);
    if (!res.affected) throw new NotFoundException(`Course ${id} not found`);
  }
}

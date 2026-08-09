import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { Department } from './entities/department.entity';
import { CreateDepartmentDto, UpdateDepartmentDto } from './dto/department.dto';

@Injectable()
export class DepartmentService {
  constructor(
    @InjectRepository(Department) private readonly repo: Repository<Department>,
  ) {}

  create(dto: CreateDepartmentDto) {
    return this.repo.save(this.repo.create(dto));
  }

  findAll(schoolId?: string) {
    return this.repo.find({ where: schoolId ? { schoolId } : {} });
  }

  async findOne(id: string) {
    const d = await this.repo.findOne({ where: { id } });
    if (!d) throw new NotFoundException(`Department ${id} not found`);
    return d;
  }

  async update(id: string, dto: UpdateDepartmentDto) {
    const d = await this.findOne(id);
    Object.assign(d, dto);
    return this.repo.save(d);
  }

  async remove(id: string) {
    const res = await this.repo.delete(id);
    if (!res.affected)
      throw new NotFoundException(`Department ${id} not found`);
  }
}

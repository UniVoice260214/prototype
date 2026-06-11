import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  Param,
  ParseUUIDPipe,
  Patch,
  Post,
} from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiParam, ApiTags } from '@nestjs/swagger';
import { Roles } from '../../common/decorators/roles.decorator';
import { SchoolService } from './school.service';
import { CreateSchoolDto, UpdateSchoolDto } from './dto/school.dto';

@ApiBearerAuth()
@ApiTags('schools')
@Controller('schools')
export class SchoolController {
  constructor(private readonly service: SchoolService) {}

  @Roles('admin')
  @Post()
  @ApiOperation({ summary: '학교 생성' })
  create(@Body() dto: CreateSchoolDto) {
    return this.service.create(dto);
  }

  @Get()
  @ApiOperation({ summary: '학교 목록 조회' })
  findAll() {
    return this.service.findAll();
  }

  @Get(':schoolId')
  @ApiOperation({ summary: '학교 1건 조회' })
  @ApiParam({ name: 'schoolId', description: '학교(School) UUID', format: 'uuid' })
  findOne(@Param('schoolId', ParseUUIDPipe) id: string) {
    return this.service.findOne(id);
  }

  @Roles('admin')
  @Patch(':schoolId')
  @ApiOperation({ summary: '학교 정보 수정' })
  @ApiParam({ name: 'schoolId', description: '학교(School) UUID', format: 'uuid' })
  update(
    @Param('schoolId', ParseUUIDPipe) id: string,
    @Body() dto: UpdateSchoolDto,
  ) {
    return this.service.update(id, dto);
  }

  @Roles('admin')
  @HttpCode(204)
  @Delete(':schoolId')
  @ApiOperation({ summary: '학교 삭제' })
  @ApiParam({ name: 'schoolId', description: '학교(School) UUID', format: 'uuid' })
  remove(@Param('schoolId', ParseUUIDPipe) id: string) {
    return this.service.remove(id);
  }
}

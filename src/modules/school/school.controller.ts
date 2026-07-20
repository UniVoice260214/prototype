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
  @ApiOperation({ summary: 'Create a school' })
  create(@Body() dto: CreateSchoolDto) {
    return this.service.create(dto);
  }

  @Roles('admin', 'professor')
  @Get()
  @ApiOperation({ summary: 'List schools' })
  findAll() {
    return this.service.findAll();
  }

  @Roles('admin', 'professor')
  @Get(':schoolId')
  @ApiOperation({ summary: 'Get a single school' })
  @ApiParam({ name: 'schoolId', description: 'School UUID', format: 'uuid' })
  findOne(@Param('schoolId', ParseUUIDPipe) id: string) {
    return this.service.findOne(id);
  }

  @Roles('admin')
  @Patch(':schoolId')
  @ApiOperation({ summary: 'Update a school' })
  @ApiParam({ name: 'schoolId', description: 'School UUID', format: 'uuid' })
  update(
    @Param('schoolId', ParseUUIDPipe) id: string,
    @Body() dto: UpdateSchoolDto,
  ) {
    return this.service.update(id, dto);
  }

  @Roles('admin')
  @HttpCode(204)
  @Delete(':schoolId')
  @ApiOperation({ summary: 'Delete a school' })
  @ApiParam({ name: 'schoolId', description: 'School UUID', format: 'uuid' })
  remove(@Param('schoolId', ParseUUIDPipe) id: string) {
    return this.service.remove(id);
  }
}

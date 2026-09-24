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
  Query,
} from '@nestjs/common';
import {
  ApiBearerAuth,
  ApiOperation,
  ApiParam,
  ApiQuery,
  ApiTags,
} from '@nestjs/swagger';
import { Roles } from '../../common/decorators/roles.decorator';
import { ProfessorService } from './professor.service';
import { CreateProfessorDto, UpdateProfessorDto } from './dto/professor.dto';

@ApiBearerAuth()
@ApiTags('professors')
@Controller('professors')
export class ProfessorController {
  constructor(private readonly service: ProfessorService) {}

  @Roles('admin')
  @Post()
  @ApiOperation({
    summary: 'Create a professor profile linked to a professor user',
  })
  create(@Body() dto: CreateProfessorDto) {
    return this.service.create(dto);
  }

  @Roles('admin', 'professor')
  @Get()
  @ApiOperation({ summary: 'List professor profiles' })
  @ApiQuery({
    name: 'departmentId',
    required: false,
    description: 'Optional department UUID filter',
  })
  findAll(@Query('departmentId') departmentId?: string) {
    return this.service.findAll(departmentId);
  }

  @Roles('admin', 'professor')
  @Get(':professorId')
  @ApiOperation({ summary: 'Get a single professor profile' })
  @ApiParam({
    name: 'professorId',
    description: 'Professor UUID',
    format: 'uuid',
  })
  findOne(@Param('professorId', ParseUUIDPipe) id: string) {
    return this.service.findOne(id);
  }

  @Roles('admin')
  @Patch(':professorId')
  @ApiOperation({ summary: 'Update a professor profile' })
  @ApiParam({
    name: 'professorId',
    description: 'Professor UUID',
    format: 'uuid',
  })
  update(
    @Param('professorId', ParseUUIDPipe) id: string,
    @Body() dto: UpdateProfessorDto,
  ) {
    return this.service.update(id, dto);
  }

  @Roles('admin')
  @HttpCode(204)
  @Delete(':professorId')
  @ApiOperation({ summary: 'Delete a professor profile' })
  @ApiParam({
    name: 'professorId',
    description: 'Professor UUID',
    format: 'uuid',
  })
  remove(@Param('professorId', ParseUUIDPipe) id: string) {
    return this.service.remove(id);
  }
}

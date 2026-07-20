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
import {
  AuthUser,
  CurrentUser,
} from '../../common/decorators/current-user.decorator';
import { Roles } from '../../common/decorators/roles.decorator';
import { GlossaryService } from './glossary.service';
import { CreateGlossaryDto, UpdateGlossaryDto } from './dto/glossary.dto';

@ApiBearerAuth()
@ApiTags('glossary')
@Controller('glossary')
export class GlossaryController {
  constructor(private readonly service: GlossaryService) {}

  @Roles('admin', 'professor')
  @Post()
  @ApiOperation({ summary: 'Create a glossary term' })
  create(@Body() dto: CreateGlossaryDto, @CurrentUser() user: AuthUser) {
    return this.service.create(dto, user);
  }

  @Roles('admin', 'professor')
  @Get()
  @ApiOperation({ summary: 'List glossary terms visible to the current user' })
  @ApiQuery({
    name: 'courseId',
    required: false,
    description: 'Optional course UUID filter',
  })
  findAll(
    @Query('courseId') courseId: string | undefined,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.findAll({ courseId }, user);
  }

  @Roles('admin', 'professor')
  @Get(':glossaryId')
  @ApiOperation({ summary: 'Get a glossary term visible to the current user' })
  @ApiParam({
    name: 'glossaryId',
    description: 'Glossary UUID',
    format: 'uuid',
  })
  findOne(
    @Param('glossaryId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.findOne(id, user);
  }

  @Roles('admin', 'professor')
  @Patch(':glossaryId')
  @ApiOperation({ summary: 'Update a glossary term' })
  @ApiParam({
    name: 'glossaryId',
    description: 'Glossary UUID',
    format: 'uuid',
  })
  update(
    @Param('glossaryId', ParseUUIDPipe) id: string,
    @Body() dto: UpdateGlossaryDto,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.update(id, dto, user);
  }

  @Roles('admin', 'professor')
  @HttpCode(204)
  @Delete(':glossaryId')
  @ApiOperation({ summary: 'Delete a glossary term' })
  @ApiParam({
    name: 'glossaryId',
    description: 'Glossary UUID',
    format: 'uuid',
  })
  remove(
    @Param('glossaryId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.remove(id, user);
  }
}

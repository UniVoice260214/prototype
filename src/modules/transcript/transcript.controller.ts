import {
  Body,
  Controller,
  Get,
  HttpCode,
  Param,
  ParseUUIDPipe,
  Post,
  Query,
} from '@nestjs/common';
import {
  ApiBearerAuth,
  ApiOperation,
  ApiParam,
  ApiTags,
} from '@nestjs/swagger';
import {
  AuthUser,
  CurrentUser,
} from '../../common/decorators/current-user.decorator';
import { Public } from '../../common/decorators/public.decorator';
import { Roles } from '../../common/decorators/roles.decorator';
import { TranscriptService } from './transcript.service';
import {
  ListTranscriptsQueryDto,
  StudentTranscriptQueryDto,
} from './dto/transcript.dto';

@ApiBearerAuth()
@ApiTags('transcripts')
@Controller('sessions/:sessionId/transcripts')
export class TranscriptController {
  constructor(private readonly service: TranscriptService) {}

  @Roles('admin', 'professor')
  @Get()
  @ApiOperation({
    summary: 'List saved transcript segments for a session (professor/admin)',
  })
  @ApiParam({ name: 'sessionId', description: 'Session UUID', format: 'uuid' })
  list(
    @Param('sessionId', ParseUUIDPipe) sessionId: string,
    @Query() query: ListTranscriptsQueryDto,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.listForUser(sessionId, query, user);
  }

  /**
   * 학생 이력 조회. joinToken 이 URL 에 노출되지 않도록 GET 쿼리 대신
   * POST body 로 받는다 (sessions/:id/token 과 같은 패턴).
   */
  @Public()
  @HttpCode(200)
  @Post('query')
  @ApiOperation({
    summary:
      'List saved transcript segments using a Student JWT or QR join token',
  })
  @ApiParam({ name: 'sessionId', description: 'Session UUID', format: 'uuid' })
  listForStudent(
    @Param('sessionId', ParseUUIDPipe) sessionId: string,
    @Body() dto: StudentTranscriptQueryDto,
    @CurrentUser() user: AuthUser | undefined,
  ) {
    const studentId = user?.type === 'student' ? user.sub : null;
    return this.service.listForStudent(sessionId, dto, studentId);
  }
}

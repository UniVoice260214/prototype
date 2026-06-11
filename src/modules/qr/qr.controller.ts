import { Controller, Get, Param, ParseUUIDPipe } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiParam, ApiTags } from '@nestjs/swagger';
import { Roles } from '../../common/decorators/roles.decorator';
import { QrService } from './qr.service';

@ApiBearerAuth()
@ApiTags('qr')
@Controller('qr')
export class QrController {
  constructor(private readonly service: QrService) {}

  @Roles('admin', 'professor')
  @Get(':sessionId')
  @ApiParam({ name: 'sessionId', description: '세션(Session) UUID', format: 'uuid' })
  @ApiOperation({
    summary: '세션 입장용 QR 생성 (JoinToken 임베드 PNG data URL 반환)',
  })
  generate(@Param('sessionId', ParseUUIDPipe) sessionId: string) {
    return this.service.generateForSession(sessionId);
  }
}

import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import {
  ArrayMinSize,
  IsArray,
  IsOptional,
  IsString,
  IsUUID,
} from 'class-validator';

export class StartSessionDto {
  @ApiProperty({ format: 'uuid' })
  @IsUUID()
  courseId: string;

  @ApiProperty({
    example: ['zh-CN', 'vi-VN', 'mn-MN'],
    description: '이 세션에서 번역해 송출할 언어 locale 목록',
  })
  @IsArray()
  @ArrayMinSize(1)
  @IsString({ each: true })
  targetLocales: string[];
}

export class IssueStudentTokenDto {
  @ApiPropertyOptional({
    description:
      'QR 입장 시 발급받은 JoinToken. Student JWT로 인증되면 생략 가능.',
  })
  @IsOptional()
  @IsString()
  joinToken?: string;

  @ApiProperty({ example: 'vi-VN' })
  @IsString()
  locale: string;
}

export class LiveKitTokenResponseDto {
  @ApiProperty()
  liveKitUrl: string;

  @ApiProperty()
  token: string;

  @ApiProperty()
  roomName: string;

  @ApiProperty()
  identity: string;
}
